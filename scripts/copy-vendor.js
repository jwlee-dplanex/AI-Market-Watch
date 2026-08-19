/**
 * node_modules에 설치된 프런트엔드 라이브러리를 static/vendor/로 복사한다.
 *
 * node_modules는 .gitignore 대상이고 배포 서버에 npm이 없을 수도 있으므로,
 * 브라우저가 실제로 받아 갈 파일만 static/vendor/에 두고 커밋한다.
 * 버전은 package.json에 고정돼 있어, 라이브러리가 새로 나와도
 * `npm install`을 다시 돌리기 전까지 화면은 바뀌지 않는다.
 *
 * 사용: npm run copy:vendor  (또는 npm run build)
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const DEST = path.join(ROOT, 'static', 'vendor');

/** [node_modules 기준 경로, static/vendor 안에 놓일 이름] */
const FILES = [
  ['htmx.org/dist/htmx.min.js', 'htmx.min.js'],
  ['alpinejs/dist/cdn.min.js', 'alpine.min.js'],
  ['lucide/dist/umd/lucide.min.js', 'lucide.min.js'],
];

fs.mkdirSync(DEST, { recursive: true });

let failed = 0;
for (const [from, to] of FILES) {
  const src = path.join(ROOT, 'node_modules', from);
  if (!fs.existsSync(src)) {
    // 경로가 틀렸거나 설치가 안 된 것이다. 조용히 넘어가면 화면이 깨진 채로 배포된다.
    console.error(`  [실패] ${from} 을(를) 찾을 수 없습니다. npm install을 먼저 실행하세요.`);
    failed += 1;
    continue;
  }
  fs.copyFileSync(src, path.join(DEST, to));
  const kb = (fs.statSync(src).size / 1024).toFixed(0);
  console.log(`  [복사] ${to}  (${kb} KB)`);
}

if (failed > 0) {
  console.error(`\n${failed}개 파일을 복사하지 못했습니다.`);
  process.exit(1);
}
console.log(`\nstatic/vendor/ 로 ${FILES.length}개 파일을 복사했습니다.`);
