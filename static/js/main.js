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
  const generateButton = document.getElementById('generateQuestions');
  const keywordInput = document.getElementById('draftKeywords');
  const draftCountSelect = document.getElementById('draftCount');
  const generatorStatus = document.getElementById('generatorStatus');

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

  function setGeneratorStatus(message, type) {
    if (!generatorStatus) return;
    generatorStatus.textContent = message;
    generatorStatus.classList.toggle('is-success', type === 'success');
    generatorStatus.classList.toggle('is-error', type === 'error');
  }

  function ensureQuestionCount(targetCount) {
    let active = activeEditors();
    const deleted = Array.from(
      formsContainer.querySelectorAll('[data-question-form]')
    ).filter(isDeleted);

    while (active.length < targetCount && deleted.length) {
      const editor = deleted.shift();
      const input = editor ? deleteInput(editor) : null;
      if (input) input.value = '';
      active = activeEditors();
    }
    while (active.length < targetCount) {
      addButton.click();
      active = activeEditors();
    }
    while (active.length > targetCount) {
      const editor = active[active.length - 1];
      const input = deleteInput(editor);
      if (input) input.value = 'on';
      active = activeEditors();
    }
    updateCreatorState();
  }

  function fillDrafts(result) {
    const drafts = Array.isArray(result.drafts) ? result.drafts : [];
    ensureQuestionCount(drafts.length);
    activeEditors().forEach(function (editor, index) {
      const draft = drafts[index];
      if (!draft) return;
      ['title', 'description', 'choice_a', 'choice_b'].forEach(function (fieldName) {
        const field = editor.querySelector('[name$="-' + fieldName + '"]');
        if (field) field.value = draft[fieldName] || '';
      });
    });

    const titleInput = document.getElementById('id_title');
    const descriptionInput = document.getElementById('id_description');
    if (titleInput && !titleInput.value.trim()) {
      titleInput.value = result.title_suggestion || '';
    }
    if (descriptionInput && !descriptionInput.value.trim()) {
      descriptionInput.value = result.description_suggestion || '';
    }
  }

  if (generateButton && keywordInput && draftCountSelect) {
    generateButton.addEventListener('click', async function () {
      const keywords = keywordInput.value.trim();
      const categorySelect = document.getElementById('id_category');
      const category = categorySelect ? categorySelect.value : '';
      if (!keywords) {
        setGeneratorStatus('먼저 한 개 이상의 키워드를 입력해주세요.', 'error');
        keywordInput.focus();
        return;
      }
      if (!category) {
        setGeneratorStatus('주제 정보에서 카테고리를 먼저 선택해주세요.', 'error');
        if (categorySelect) categorySelect.focus();
        return;
      }

      const originalHtml = generateButton.innerHTML;
      generateButton.disabled = true;
      generateButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>초안 만드는 중';
      setGeneratorStatus('키워드를 바탕으로 안전한 질문 초안을 구성하고 있습니다.', '');

      const csrfInput = form.querySelector('[name="csrfmiddlewaretoken"]');
      const body = new URLSearchParams({
        keywords: keywords,
        count: draftCountSelect.value,
        category: category
      });

      try {
        const response = await fetch(generateButton.dataset.generateUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
            'X-CSRFToken': csrfInput ? csrfInput.value : ''
          },
          body: body.toString()
        });
        const result = await response.json();
        if (!response.ok) {
          throw new Error(result.error || '문항을 만들지 못했습니다.');
        }
        fillDrafts(result);
        const generatorLabel = result.source === 'ai' ? 'AI가' : '안전한 기본 생성기가';
        setGeneratorStatus(
          generatorLabel + ' ' + result.drafts.length
            + '개 질문 초안을 채웠습니다. 내용을 확인하고 원하는 표현으로 수정해주세요.',
          'success'
        );
      } catch (error) {
        setGeneratorStatus(
          error instanceof Error ? error.message : '문항을 만들지 못했습니다. 다시 시도해주세요.',
          'error'
        );
      } finally {
        generateButton.disabled = false;
        generateButton.innerHTML = originalHtml;
      }
    });
  }

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

function initWelcome() {
  const enter = document.getElementById('welcomeEnter');
  if (!enter) return;

  let entering = false;
  enter.addEventListener('click', function (event) {
    event.preventDefault();
    if (entering) return;
    entering = true;
    document.body.classList.add('is-entering');
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.setTimeout(function () {
      window.location.assign(enter.dataset.enterUrl);
    }, reduceMotion ? 80 : 950);
  });
}

function initAnalysisTabs() {
  const tabs = document.querySelectorAll('[data-analysis-tab]');
  const panels = document.querySelectorAll('[data-analysis-panel]');
  if (!tabs.length || !panels.length) return;

  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      const target = tab.dataset.analysisTab;
      tabs.forEach(function (candidate) {
        const active = candidate === tab;
        candidate.classList.toggle('active', active);
        candidate.setAttribute('aria-selected', String(active));
      });
      panels.forEach(function (panel) {
        panel.hidden = panel.dataset.analysisPanel !== target;
      });
    });
  });
}

function initInstantSearch() {
  const form = document.getElementById('instantSearchForm');
  const input = document.getElementById('instantKeywords');
  const submitButton = document.getElementById('instantSearchButton');
  const keywordButtons = document.querySelectorAll('[data-instant-keyword]');
  if (!form || !input || !submitButton) return;

  keywordButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      input.value = button.dataset.instantKeyword || '';
      input.focus();
    });
  });

  form.addEventListener('submit', function () {
    if (!input.value.trim()) return;
    submitButton.disabled = true;
    submitButton.innerHTML = (
      '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>'
      + '<span>게임 만드는 중</span>'
    );
  });
}

function initInstantAnswer() {
  const form = document.getElementById('instantAnswerForm');
  const choiceInput = document.getElementById('instantChoiceInput');
  const status = document.getElementById('instantAnswerStatus');
  const buttons = document.querySelectorAll('[data-instant-choice]');
  if (!form || !choiceInput || !buttons.length) return;

  let submitting = false;
  buttons.forEach(function (button) {
    button.addEventListener('click', function () {
      if (submitting) return;
      submitting = true;
      const choiceCode = button.dataset.instantChoice || '';
      choiceInput.value = choiceCode;
      buttons.forEach(function (candidate) {
        candidate.disabled = true;
        candidate.classList.toggle('is-selected', candidate === button);
      });
      if (status) status.textContent = '선택 완료! 다음 문항으로 이동합니다…';
      window.setTimeout(function () {
        form.submit();
      }, 180);
    });
  });
}

document.addEventListener('DOMContentLoaded', initWelcome);
document.addEventListener('DOMContentLoaded', initAnalysisTabs);
document.addEventListener('DOMContentLoaded', initInstantSearch);
document.addEventListener('DOMContentLoaded', initInstantAnswer);
