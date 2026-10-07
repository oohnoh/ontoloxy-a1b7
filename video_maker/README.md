# video_maker: 이미지와 TTS로 슬라이드 쇼츠 영상 자동 생성

문장마다 TTS 음성을 만들고 이미지 수십 장을 생성합니다. 각 이미지에는 슬라이드·켄번즈 애니메이션을 넣고, 음성 길이에 맞춰 이미지 전환을 자동으로 맞춘 30~60초 영상(mp4)을 만듭니다.

```
스크립트(YAML/TXT)
  ├─ 문장별 TTS ─────────► 길이 측정 → 30~60초에 맞게 말 속도/쉼 자동 조절
  ├─ 이미지 N장 생성 ────► 문장 음성 길이 ÷ 그 문장의 이미지 수 = 이미지당 노출 시간
  ├─ 이미지마다 줌인/줌아웃/좌우·상하 패닝 (Ken Burns)
  ├─ 이미지 사이 슬라이드 전환 (slideleft/slideup/smoothleft …)
  ├─ 자막 (문장을 짧게 나눠 음성 타이밍에 맞춤, 팝인 효과)
  └─ 나레이션 + (선택) BGM 믹스 → output/video.mp4
```

## 설치

```bash
# ffmpeg 필요 (macOS: brew install ffmpeg / Ubuntu: apt install ffmpeg / Windows: winget install ffmpeg)
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...      # AI 이미지 생성(--images openai)에 필요
```

## 사용법

```bash
# 기본: edge-tts(무료 한국어 음성) + OpenAI 이미지, 세로 1080x1920, 30~60초
python -m video_maker examples/sample.yaml -o output/space.mp4

# 이미지 없이 먼저 타이밍·효과만 미리보기 (오프라인, 무료)
python -m video_maker examples/sample.yaml --images placeholder -o output/preview.mp4

# 직접 준비한 이미지 폴더 사용 (파일명 순서대로)
python -m video_maker examples/sample.yaml --images folder --image-dir my_images/

# 텍스트 파일(한 줄 = 한 장면), 장면당 이미지 3장, 가로 영상, BGM 추가
python -m video_maker script.txt --images-per-scene 3 --size 1920x1080 --bgm bgm.mp3
```

### 주요 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--tts` | `edge` | `edge`(무료) / `openai` / `silent`(테스트용 무음) |
| `--voice` | `ko-KR-SunHiNeural` | edge: `ko-KR-InJoonNeural`(남), `ko-KR-HyunsuNeural` 등 |
| `--images` | `openai` | `openai`(gpt-image-1) / `placeholder` / `folder` |
| `--images-per-scene` | `2` | 스크립트에 images가 없을 때 문장당 이미지 수 |
| `--transition` | `slide` | `slide` / `fade` / `mix` / `none` / ffmpeg xfade 이름(`wipeleft` 등) |
| `--duration` | `30-60` | 목표 길이(초). 벗어나면 말 속도 0.9~1.4배, 쉼 길이를 자동 조절 |
| `--size` | `1080x1920` | 해상도 |
| `--no-subtitles` | 끔 | 자막 비활성화 |
| `--bgm`, `--bgm-volume` | 없음, `0.12` | 배경음악(반복 재생, 끝에서 페이드아웃) |

## 스크립트 형식

[`examples/sample.yaml`](../examples/sample.yaml) 참고:

```yaml
voice: ko-KR-SunHiNeural
size: [1080, 1920]
duration: [30, 60]
images_per_scene: 3
style: cinematic, ultra detailed, vertical composition, no text   # 모든 프롬프트 뒤에 붙음
scenes:
  - text: 첫째, 우주의 95퍼센트는 암흑 물질과 암흑 에너지입니다.   # 이 문장이 TTS + 자막
    images:                                                       # 문장 음성 동안 순서대로 표시
      - invisible dark matter web connecting galaxies
      - galaxy cluster bending light
  - text: 이미지 프롬프트를 생략하면 문장 자체가 프롬프트가 됩니다.
  - text: 개수만 지정할 수도 있습니다.
    images: 4
```

**분량 기준:** 한국어 TTS는 초당 약 6~7자입니다. 30~60초 영상은 공백 제외 200~350자 정도가 적당하고, 이미지 20~40장이면 장당 1.5초 안팎으로 빠르게 넘어갑니다.

## 결과물

- `output/video.mp4`: 최종 영상
- `output/video_work/`: 캐시 폴더. 이미지는 재사용되므로 스크립트나 효과만 바꿔 다시 돌려도 이미지를 새로 생성하지 않습니다. 이미지를 바꾸려면 `images/img_XXX.png`를 지우거나 덮어쓰세요.
  - `timeline.json`: 이미지별 시작 시간, 길이, 모션, 전환 효과
  - `captions.ass`: 자막 파일
  - `narration.wav`: 나레이션 음성
