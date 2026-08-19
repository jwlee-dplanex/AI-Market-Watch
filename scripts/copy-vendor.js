/**
 * 빌드 시 static/ 아래로 복사해야 하는 파일들을 한 번에 처리한다.
 *
 * 1. node_modules에 설치된 프런트엔드 라이브러리 → static/vendor/
 *    node_modules는 .gitignore 대상이고 배포 서버에 npm이 없을 수도 있으므로,
 *    브라우저가 실제로 받아 갈 파일만 static/vendor/에 두고 커밋한다.
 *    버전은 package.json에 고정돼 있어, 라이브러리가 새로 나와도
 *    `npm install`을 다시 돌리기 전까지 화면은 바뀌지 않는다.
 *
 * 2. 서비스 소개 자료(docs/reports/) → static/docs/
 *    docs/는 정적 서빙 대상이 아니라서(Django STATICFILES_DIRS는 static/만 본다)
 *    사이드바 "서비스 소개" 모달의 "전체 소개 자료 보기" 링크가 가리킬 자리가 없었다.
 *    수동 복사로 두면 문서를 고칠 때마다 복사를 잊기 쉬워서(2026-08-19 PE 판단)
 *    라이브러리 복사와 같은 방식으로 빌드 스크립트에 묶는다. 원본 파일명은 한글
 *    ("AI_Market_Watch_서비스소개.html")이라 URL 인코딩 문제를 피하려고 복사본만
 *    ASCII 파일명으로 바꾼다 — 원본 파일명 자체는 그대로 둔다(docs/ 쪽 관례 유지).
 *
 * 사용: npm run copy:vendor  (또는 npm run build)
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

/** [node_modules 기준 경로, static/vendor 안에 놓일 이름] */
const VENDOR_FILES = [
  ['htmx.org/dist/htmx.min.js', 'htmx.min.js'],
  ['alpinejs/dist/cdn.min.js', 'alpine.min.js'],
  ['lucide/dist/umd/lucide.min.js', 'lucide.min.js'],
];

/** [프로젝트 루트 기준 원본 경로, static/docs 안에 놓일 이름] */
const DOC_FILES = [
  ['docs/reports/AI_Market_Watch_서비스소개.html', 'AI_Market_Watch_service_intro.html'],
];

function copyAll(destDirParts, entries, baseDir) {
  const dest = path.join(ROOT, ...destDirParts);
  fs.mkdirSync(dest, { recursive: true });

  let failed = 0;
  for (const [from, to] of entries) {
    const src = path.join(ROOT, baseDir, from);
    if (!fs.existsSync(src)) {
      // 경로가 틀렸거나 원본이 없는 것이다. 조용히 넘어가면 화면/링크가 깨진 채로 배포된다.
      console.error(`  [실패] ${from} 을(를) 찾을 수 없습니다.`);
      failed += 1;
      continue;
    }
    fs.copyFileSync(src, path.join(dest, to));
    const kb = (fs.statSync(src).size / 1024).toFixed(0);
    console.log(`  [복사] ${to}  (${kb} KB)`);
  }
  return failed;
}

let failed = 0;
failed += copyAll(['static', 'vendor'], VENDOR_FILES, 'node_modules');
failed += copyAll(['static', 'docs'], DOC_FILES, '.');

if (failed > 0) {
  console.error(`\n${failed}개 파일을 복사하지 못했습니다. node_modules 라이브러리라면 npm install을 먼저 실행하세요.`);
  process.exit(1);
}
console.log(`\nstatic/vendor/, static/docs/ 로 ${VENDOR_FILES.length + DOC_FILES.length}개 파일을 복사했습니다.`);
