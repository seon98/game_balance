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

function initGameCreator() {
  const form = document.getElementById('gameSetForm');
  const formsContainer = document.getElementById('questionForms');
  const addButton = document.getElementById('addQuestion');
  const emptyTemplate = document.getElementById('emptyQuestionForm');
  const totalFormsInput = document.getElementById('id_questions-TOTAL_FORMS');
  const counter = document.getElementById('activeQuestionCount');

  if (!form || !formsContainer || !addButton || !emptyTemplate || !totalFormsInput) {
    return;
  }

  const minQuestions = 7;
  const maxQuestions = 10;

  function deleteInput(editor) {
    return editor.querySelector('input[name$="-DELETE"]');
  }

  function isDeleted(editor) {
    const input = deleteInput(editor);
    if (!input) return false;
    const value = input.value.toLowerCase();
    return value === 'on' || value === 'true' || value === '1';
  }

  function activeEditors() {
    return Array.from(formsContainer.querySelectorAll('[data-question-form]')).filter(
      function (editor) {
        return !isDeleted(editor);
      }
    );
  }

  function updateCreatorState() {
    const active = activeEditors();
    active.forEach(function (editor, index) {
      const number = editor.querySelector('.question-index');
      if (number) number.textContent = String(index + 1);
    });

    formsContainer.querySelectorAll('[data-question-form]').forEach(function (editor) {
      editor.hidden = isDeleted(editor);
    });

    const count = active.length;
    if (counter) counter.textContent = String(count);
    addButton.disabled = count >= maxQuestions;
    active.forEach(function (editor) {
      const removeButton = editor.querySelector('.remove-question');
      if (removeButton) removeButton.disabled = count <= minQuestions;
    });
  }

  function bindRemoveButton(editor) {
    const removeButton = editor.querySelector('.remove-question');
    if (!removeButton || removeButton.dataset.bound === 'true') return;
    removeButton.dataset.bound = 'true';
    removeButton.addEventListener('click', function () {
      if (activeEditors().length <= minQuestions) return;
      const input = deleteInput(editor);
      if (input) input.value = 'on';
      updateCreatorState();
    });
  }

  formsContainer.querySelectorAll('[data-question-form]').forEach(bindRemoveButton);

  addButton.addEventListener('click', function () {
    if (activeEditors().length >= maxQuestions) return;
    const index = Number.parseInt(totalFormsInput.value, 10);
    const html = emptyTemplate.innerHTML.replaceAll('__prefix__', String(index));
    formsContainer.insertAdjacentHTML('beforeend', html);
    totalFormsInput.value = String(index + 1);
    const editor = formsContainer.lastElementChild;
    if (editor) bindRemoveButton(editor);
    updateCreatorState();
  });

  const basisSelect = document.getElementById('id_content_basis');
  const referenceGroup = document.getElementById('referenceUrlGroup');
  function updateReferenceState() {
    if (!basisSelect || !referenceGroup) return;
    referenceGroup.classList.toggle(
      'reference-required',
      basisSelect.value === 'SOURCED'
    );
  }
  if (basisSelect) {
    basisSelect.addEventListener('change', updateReferenceState);
    updateReferenceState();
  }

  form.addEventListener('submit', function (event) {
    const count = activeEditors().length;
    if (count < minQuestions || count > maxQuestions) {
      event.preventDefault();
      alert('질문은 7개 이상 10개 이하로 구성해주세요.');
    }
  });

  updateCreatorState();
}

document.addEventListener('DOMContentLoaded', initGameCreator);
