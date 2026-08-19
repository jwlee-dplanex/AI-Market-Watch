/**
 * Tailwind 설정 — templates/base.html 안에 있던 Play CDN용 `tailwind.config`를
 * 그대로 옮긴 것이다. 값을 바꾸면 화면 색·모서리·폰트가 전부 바뀌므로,
 * 디자인 시스템(docs/design.md 1.1)을 먼저 고치고 여기에 반영한다.
 *
 * ⚠️ Tailwind v3로 고정한다(3.4.17). Play CDN(cdn.tailwindcss.com)이 v3 기반이라
 * v4로 올리면 클래스 동작이 달라져 지금 화면이 그대로 재현되지 않는다.
 * v4 전환은 화면 전수 확인을 동반하는 별도 작업이다.
 */
module.exports = {
  /**
   * ⚠️ 여기 없는 파일의 클래스는 최종 CSS에서 빠진다.
   * Play CDN은 브라우저에서 DOM을 훑어 실시간 생성했지만, CLI 빌드는
   * 빌드 시점에 아래 경로만 훑는다. 템플릿을 새 위치에 만들면 여기에 추가한다.
   */
  content: [
    './templates/**/*.html',
    './apps/**/*.html',
    './apps/**/*.py',
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: '#60269E', dark: '#401771', hover: '#4C1C80' },
        accent:  { DEFAULT: '#93D500' },
        teal:    { DEFAULT: '#00AF9A', hover: '#009583' },
      },
      borderRadius: { DEFAULT: '10px' },
      fontFamily: {
        sans:  ['Noto Sans KR', 'Inter', 'sans-serif'],
        serif: ['Noto Serif KR', 'Source Serif 4', 'serif'],
        mono:  ['JetBrains Mono', 'monospace'],
      },
    },
  },
  /**
   * 문자열을 조립해 만드는 클래스(예: `'bg-' + color`)는 위 content 스캔으로
   * 잡히지 않는다. 그런 패턴이 발견되면 여기에 명시한다.
   * 현재는 비어 있으며, 빌드 후 화면 전수 확인에서 빠진 클래스가 나오면 채운다.
   */
  safelist: [],
  plugins: [],
};
