# 서재 폴더

리더가 책 목록을 보여 주는 폴더입니다. 책마다 폴더 하나를 두고 그 안에 Markdown과 그림을 넣습니다.

```
library/
  비트겐슈타인/
    비트겐슈타인.md
    비트겐슈타인.notes.json     (리더가 만드는 주석 파일)
    assets/…                    (Markdown이 링크하는 그림)
  index.json                    (웹 서버로 올릴 때 쓰는 목록, library.py가 만듦)
```

- 책 넣기: `python reader/library.py add "D:\ebook\비트겐슈타인"` — Markdown, 주석 파일, 링크된 그림만 복사합니다(PDF·캡처 원본은 두고 옴)
- 목록 다시 만들기: `python reader/library.py`
- 리더에서: 시작 화면의 "서재 폴더 연결"로 이 폴더를 한 번 고르면 다음부터 책 목록이 나옵니다

이 폴더의 책은 저작권이 있는 캡처본이라 git에 올리지 않습니다(`.gitignore`). 이 안내문만 저장소에 들어갑니다.
