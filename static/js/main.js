'use strict';

// 클립보드 복사 (결과 페이지에서도 사용)
function copyShareText() {
  const el = document.getElementById('shareText');
  if (!el) return;

  const text = el.innerText.trim();

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(onCopySuccess).catch(onCopyFallback(text));
  } else {
    onCopyFallback(text)();
  }
}

function onCopySuccess() {
  const btn = document.getElementById('copyBtn');
  if (!btn) return;
  const original = btn.innerHTML;
  btn.innerHTML = '<i class="bi bi-check2 me-1"></i>복사됨!';
  btn.classList.replace('btn-outline-secondary', 'btn-success');
  setTimeout(function () {
    btn.innerHTML = original;
    btn.classList.replace('btn-success', 'btn-outline-secondary');
  }, 2000);
}

function onCopyFallback(text) {
  return function () {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      onCopySuccess();
    } catch (_) {
      alert('복사에 실패했습니다. 직접 선택해서 복사해주세요.');
    }
  };
}
