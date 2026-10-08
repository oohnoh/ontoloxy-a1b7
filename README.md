# ontoloxy-a1b7
core project about a1b7

## video_maker: AI 이미지 + TTS 슬라이드 쇼츠 자동 생성

문장별 TTS 음성에 맞춰 이미지 수십 장을 슬라이드/켄번즈 애니메이션으로 이어 붙여 30~60초 영상을 만듭니다.

```bash
pip install -r requirements.txt
python -m video_maker examples/sample.yaml -o output/video.mp4
```

자세한 내용: [video_maker/README.md](video_maker/README.md)


# ebook-auto-generator

## Overview
This project is a tool that automatically generates PDF/EPUB ebooks from text or markdown files.

## Features
- Automatic conversion from Markdown to PDF / EPUB
- Auto-generation of cover page, table of contents, and chapter structure
- OpenAI API integration for content completion and proofreading
- Template-based layout customization

## Usage
1. Clone the repository: `git clone https://github.com/your-username/ebook-auto-generator`
2. Install dependencies: `pip install -r requirements.txt`
3. Prepare input: place your `.md` file in the `input/` folder
4. Run: `python generate.py --input input/draft.md --format pdf`
5. Check output: find the generated ebook in the `output/` folder

## License
MIT License
