import os
import shutil
import threading
import urllib.parse
import uuid
import aspose.words as aw
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware

try:
    import win32com.client as win32  # pywin32
except Exception:
    win32 = None

app = FastAPI(title="AI 이의 있쏘! 문서 변환 엔진")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_STORAGE = os.path.join(BASE_DIR, "temp_storage")
os.makedirs(TEMP_STORAGE, exist_ok=True)

# 확장자별 처리 전략 분기 상수.
ASPOSE_EXTENSIONS = {".doc", ".docx"}
HWP_EXTENSIONS = {".hwp", ".hwpx"}
PASSTHROUGH_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = ASPOSE_EXTENSIONS | HWP_EXTENSIONS | PASSTHROUGH_EXTENSIONS
# HWP COM 자동화는 동시 접근 시 불안정해서 전역 락으로 직렬화한다.
HWP_COM_LOCK = threading.Lock()


def _convert_hwp_with_hancom(input_path: str, output_path: str):
    """한글 COM 자동화로 HWP/HWPX를 PDF로 변환합니다."""
    if win32 is None:
        raise RuntimeError(
            "pywin32가 설치되지 않았습니다. `pip install pywin32` 후 다시 시도하세요."
        )

    hwp = None
    try:
        # gencache 손상(CLSIDToClassMap/MinorVersion) 이슈를 피하기 위해
        # Hancom COM 객체는 Dispatch 경로를 우선 사용한다.
        hwp = win32.Dispatch("HWPFrame.HwpObject")

        hwp.XHwpWindows.Item(0).Visible = False

        # 한글 보안 경고창 억제 (환경에 따라 무시될 수 있음)
        try:
            hwp.RegisterModule("FilePathCheckDLL", "FileAuto")
        except Exception:
            pass

        # 한글 버전별 Open 시그니처 차이를 흡수한다.
        opened = False
        open_errors = []
        for open_args in (
            (input_path, "HWP", "forceopen:true"),
            (input_path, "HWP", ""),
            (input_path,),
        ):
            try:
                hwp.Open(*open_args)
                opened = True
                break
            except Exception as e:
                open_errors.append(str(e))

        if not opened:
            raise RuntimeError(f"한글 문서 열기 실패: {' | '.join(open_errors)}")

        # 한글 버전별 PDF 저장 API 시그니처 차이를 흡수한다.
        save_errors = []

        try:
            hwp.HAction.GetDefault("FileSaveAsPdf", hwp.HParameterSet.HFileOpenSave.HSet)
            hwp.HParameterSet.HFileOpenSave.filename = output_path
            hwp.HParameterSet.HFileOpenSave.Format = "PDF"
            hwp.HAction.Execute("FileSaveAsPdf", hwp.HParameterSet.HFileOpenSave.HSet)
            return
        except Exception as e:
            save_errors.append(f"HAction FileSaveAsPdf 실패: {e}")

        for save_args in (
            (output_path, "PDF", ""),
            (output_path, "PDF"),
            (output_path,),
        ):
            try:
                hwp.SaveAs(*save_args)
                return
            except Exception as e:
                save_errors.append(f"SaveAs{save_args} 실패: {e}")

        raise RuntimeError(f"PDF 저장 실패: {' | '.join(save_errors)}")
    finally:
        if hwp is not None:
            try:
                hwp.Quit()
            except Exception:
                pass


@app.post("/transform")
async def transform_document(file: UploadFile = File(...)):
    # 원본 파일명 기반으로 브라우저 표시용 PDF 이름을 만든다.
    file_name = file.filename or "document"
    name_without_ext, file_ext = os.path.splitext(file_name)
    file_ext = file_ext.lower()
    quoted_filename = urllib.parse.quote(f"{name_without_ext}.pdf")

    if file_ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 형식입니다: {file_ext}")

    unique_id = uuid.uuid4().hex
    input_path = os.path.join(TEMP_STORAGE, f"{unique_id}_input{file_ext}")
    output_path = os.path.join(TEMP_STORAGE, f"{unique_id}_output.pdf")

    try:
        # 업로드 스트림을 임시 파일로 저장한다.
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        if file_ext in PASSTHROUGH_EXTENSIONS:
            # PDF는 변환 없이 그대로 반환한다.
            target_path = input_path
        elif file_ext in HWP_EXTENSIONS:
            # COM 객체는 동시 접근 시 불안정하므로 직렬화
            with HWP_COM_LOCK:
                _convert_hwp_with_hancom(input_path, output_path)
            target_path = output_path
        else:
            # DOC/DOCX는 Aspose.Words 경로 사용
            doc = aw.Document(input_path)
            save_options = aw.saving.PdfSaveOptions()
            doc.save(output_path, save_options)
            target_path = output_path

        with open(target_path, "rb") as f:
            content = f.read()

        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f"inline; filename=converted.pdf; filename*=UTF-8''{quoted_filename}"
                )
            },
        )
    except Exception as e:
        print(f"변환 중 발생한 에러: {e}")
        raise HTTPException(status_code=500, detail=f"문서 변환 실패: {e}")
    finally:
        # 요청 종료 후 임시 입력/출력 파일을 정리한다.
        for path in (input_path, output_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.document_transform:app", host="127.0.0.1", port=8001, reload=True)
