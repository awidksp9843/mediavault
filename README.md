# MediaVault

로컬 미디어 파일 관리 웹 대시보드. 메타데이터(Exif/XMP) 태깅, AI 자동 분류, 실시간 파일 동기화를 지원합니다.

## 사전 요구사항

- Python 3.10+
- Node.js 18+
- FFmpeg (시스템 PATH에 설치)
- ExifTool (시스템 PATH에 설치, Phase 4)

## 설치 및 실행

### 백엔드

```bash
python -m venv .venv
.\.venv\Scripts\activate  # Windows
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

### 접속

브라우저에서 `http://localhost:5173` 접속
