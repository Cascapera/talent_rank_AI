// Tela da vaga (/vagas/<id>/). Extraido de templates/core/job_detail.html em R-27.
//
// Movimentacao pura: o bloco <script> inline nao tinha nenhuma tag Django dentro —
// todo dado dinamico ja vinha por atributo data-* no HTML. A unica transformacao
// aplicada foi tirar 4 espacos de recuo de cada linha.

// R-42: os detalhes de erro existiam no payload e nunca chegavam a tela — ela via
// "1 erro(s)" sem saber qual curriculo ficou de fora, nem como reenviar o certo.
//
// `escaparHtml` e obrigatorio aqui: estes textos carregam nome de arquivo e mensagem de
// excecao, e tudo isto entra por innerHTML.
function escaparHtml(texto) {
  const div = document.createElement('div');
  div.textContent = texto == null ? '' : String(texto);
  return div.innerHTML;
}

function listaDeErros(detalhes) {
  if (!detalhes || !detalhes.length) return '';
  const itens = detalhes.map(d => `<li>${escaparHtml(d)}</li>`).join('');
  return `<ul style="margin: 6px 0 0; padding-left: 18px; font-size: 12px; color: #d32f2f;">${itens}</ul>`;
}

// R-44: falha de rede nao e resposta — e ausencia dela.
//
// Os polls de status se reagendavam SO dentro do ramo `running`. Um `fetch` que falhasse
// (502 do Nginx enquanto o servico reinicia, ou conexao recusada) caia no `return` ou no
// `catch` vazio e **matava o laco para sempre**: a tela congelava no contador e nunca mais
// perguntava nada, mesmo depois de o servidor voltar.
//
// O caso em que isso doi e exatamente o caso que o R-20b existe para avisar — o deploy
// reiniciando o servico no meio de uma importacao. O backend passava a responder
// "interrompida" e ninguem estava ouvindo. Achado na validacao manual de 2026-08-19.
//
// 5s em vez de 2s de proposito: se o servidor esta fora, insistir mais rapido nao o traz
// de volta mais cedo.
function reagendarPoll(poll) {
  setTimeout(poll, 5000);
}

const importStatusEl = document.getElementById('importStatus');
if (importStatusEl) {
  const statusUrl = importStatusEl.getAttribute('data-status-url');
  const poll = async () => {
    try {
      const resp = await fetch(statusUrl, { cache: 'no-store' });
      if (!resp.ok) { reagendarPoll(poll); return; }
      const data = await resp.json();
      if (data.status === 'running') {
        const total = data.total ?? '?';
        const processed = data.processed ?? 0;
        const errors = data.errors ?? 0;
        let html = `<strong style="color: var(--primary);">Importação em andamento:</strong> ${processed}/${total}`;
        if (errors > 0) {
          html += ` <span style="color: #d32f2f;">(${errors} erro(s))</span>`;
        }
        html += listaDeErros(data.error_details);
        importStatusEl.innerHTML = html;
        importStatusEl.style.color = 'var(--text)';
        setTimeout(poll, 2000);
      } else if (data.status === 'completed') {
        const result = data.result || {};
        const created = result.created || 0;
        const updated = result.updated || 0;
        const unchanged = result.unchanged || 0;
        const skipped = result.skipped || 0;
        const errors = result.errors || 0;
        let html = `<strong style="color: var(--primary);">Importação concluída.</strong>`;
        html += `<div style="margin-top: 6px; font-size: 12px; color: var(--muted);">`;
        html += `${created} criados, ${updated} atualizados, ${unchanged} sem alteração, ${skipped} ignorados`;
        if (errors > 0) {
          html += ` <span style="color: #d32f2f;">, ${errors} erro(s)</span>`;
        }
        html += `</div>`;
        html += listaDeErros(result.error_details);
        importStatusEl.innerHTML = html;
        importStatusEl.style.color = 'var(--text)';
      } else if (data.status === 'error') {
        const message = data.message || 'Erro desconhecido';
        importStatusEl.innerHTML = `<strong style="color: #d32f2f;">Falha na importação:</strong> ${message}`;
        importStatusEl.style.color = 'var(--text)';
      }
    } catch (err) {
      reagendarPoll(poll);
    }
  };
  poll();
}

// Função para obter CSRF token
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}


const generateBooleanBtn = document.getElementById('generateBooleanBtn');
if (generateBooleanBtn) {
  const booleanTextEl = document.getElementById('booleanSearchText');
  const booleanStatusEl = document.getElementById('booleanSearchStatus');
  generateBooleanBtn.addEventListener('click', async () => {
    const url = generateBooleanBtn.getAttribute('data-url');
    generateBooleanBtn.disabled = true;
    generateBooleanBtn.textContent = 'Criando...';
    if (booleanStatusEl) {
      booleanStatusEl.textContent = 'Gerando busca booleana...';
    }
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCookie('csrftoken'),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({}),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        throw new Error(data.error || 'Erro ao gerar busca booleana.');
      }
      if (booleanTextEl) {
        booleanTextEl.textContent = data.boolean_search || 'Nenhuma busca definida.';
      }
      if (booleanStatusEl) {
        booleanStatusEl.textContent = 'Busca booleana atualizada.';
      }
    } catch (err) {
      if (booleanStatusEl) {
        booleanStatusEl.textContent = err.message || 'Falha ao gerar busca booleana.';
      }
    } finally {
      generateBooleanBtn.disabled = false;
      generateBooleanBtn.textContent = 'Criar busca';
    }
  });
}

// Tenta obter CSRF token do cookie ou do input hidden
function getCSRFToken() {
  let token = getCookie('csrftoken');
  if (!token) {
    const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
    if (csrfInput) {
      token = csrfInput.value;
    }
  }
  return token;
}

// Atualização de status do candidato
document.querySelectorAll('.status-select').forEach(select => {
  select.addEventListener('change', async function() {
    const candidateJobId = this.getAttribute('data-candidate-job-id');
    const jobId = this.getAttribute('data-job-id');
    const newStatus = this.value;
    const originalValue = this.getAttribute('data-original-value') || '';
    
    // Desabilita o select durante a requisição
    this.disabled = true;
    this.style.opacity = '0.6';
    
    try {
      const formData = new FormData();
      formData.append('pipeline_status', newStatus);
      const csrftoken = getCSRFToken();
      
      if (!csrftoken) {
        throw new Error('Token CSRF não encontrado. Recarregue a página.');
      }
      
      formData.append('csrfmiddlewaretoken', csrftoken);
      
      const response = await fetch(`/vagas/${jobId}/candidatos/${candidateJobId}/status/`, {
        method: 'POST',
        body: formData,
        headers: {
          'X-CSRFToken': csrftoken
        },
        credentials: 'same-origin'
      });
      
      const responseData = await response.json().catch(() => ({}));
      
      if (!response.ok) {
        throw new Error(responseData.error || `Erro ${response.status}: ${response.statusText}`);
      }
      
      // Atualiza o valor original para o novo status
      this.setAttribute('data-original-value', newStatus);
      
      // Se o status for CANDIDATO_PRONTO e houver ready_at, atualiza a coluna
      if (responseData.ready_at) {
        const row = this.closest('tr');
        const readyAtCell = row.querySelector('.ready-at-cell');
        if (readyAtCell) {
          readyAtCell.textContent = responseData.ready_at;
        }
      }

      // Atualiza célula de parecer: mostra botão se status for ENVIADO_GESTOR ou ENVIADO_CLIENTE
      const row = this.closest('tr');
      const parecerCell = row ? row.querySelector('.parecer-cell') : null;
      if (parecerCell) {
        const showBtn = newStatus === 'ENVIADO_GESTOR' || newStatus === 'ENVIADO_CLIENTE';
        if (showBtn) {
          const cjid = parecerCell.getAttribute('data-candidate-job-id');
          const jid = parecerCell.getAttribute('data-job-id');
          const cname = parecerCell.getAttribute('data-candidate-name') || 'Candidato';
          parecerCell.innerHTML = `<button type="button" class="btn btn-parecer" data-candidate-job-id="${cjid}" data-job-id="${jid}" data-candidate-name="${cname}" style="padding: 4px 8px; font-size: 11px;">Gerar parecer</button>`;
          parecerCell.querySelector('.btn-parecer')?.addEventListener('click', (function(jid, cjid, cname) {
            return function() {
              parecerJobId = jid;
              parecerCandidateJobId = cjid;
              parecerCandidateName.textContent = cname || 'Candidato';
              hideParecerStates();
              parecerLoading.style.display = 'block';
              parecerModalOverlay.classList.add('active');
              fetchParecerStatus().then(data => {
                parecerLoading.style.display = 'none';
                if (data && data.status === 'completed' && data.parecer) {
                  showParecerResult(data.parecer, data.parecer_type);
                } else {
                  showParecerTypeForm(data?.parecer_type || null);
                }
              }).catch(() => {
                parecerLoading.style.display = 'none';
                showParecerTypeForm(null);
              });
            };
          })(jid, cjid, cname));
        } else {
          parecerCell.textContent = '-';
        }
      }
      
      // Feedback visual de sucesso
      this.style.borderColor = 'var(--primary)';
      setTimeout(() => {
        this.style.borderColor = 'var(--border)';
      }, 1000);
      
    } catch (error) {
      console.error('Erro ao atualizar status:', error);
      // Reverte para o valor original
      this.value = originalValue;
      alert('Erro ao atualizar status: ' + error.message);
    } finally {
      this.disabled = false;
      this.style.opacity = '1';
    }
  });
  
  // Salva o valor original ao carregar
  select.setAttribute('data-original-value', select.value);
});

// Atualização de status da vaga
document.querySelectorAll('.job-status-select').forEach(select => {
  select.addEventListener('change', async function() {
    const jobId = this.getAttribute('data-job-id');
    const newStatus = this.value;
    const originalValue = this.getAttribute('data-original-value') || '';
    
    // Desabilita o select durante a requisição
    this.disabled = true;
    this.style.opacity = '0.6';
    
    try {
      const formData = new FormData();
      formData.append('status', newStatus);
      const csrftoken = getCSRFToken();
      
      if (!csrftoken) {
        throw new Error('Token CSRF não encontrado. Recarregue a página.');
      }
      
      formData.append('csrfmiddlewaretoken', csrftoken);
      
      const response = await fetch(`/vagas/${jobId}/status/`, {
        method: 'POST',
        body: formData,
        headers: {
          'X-CSRFToken': csrftoken
        },
        credentials: 'same-origin'
      });
      
      const responseData = await response.json().catch(() => ({}));
      
      if (!response.ok) {
        throw new Error(responseData.error || `Erro ${response.status}: ${response.statusText}`);
      }
      
      // Atualiza o valor original para o novo status
      this.setAttribute('data-original-value', newStatus);
      
      // Feedback visual de sucesso
      this.style.borderColor = 'var(--primary)';
      setTimeout(() => {
        this.style.borderColor = 'var(--border)';
      }, 1000);
      
    } catch (error) {
      console.error('Erro ao atualizar status da vaga:', error);
      // Reverte para o valor original
      this.value = originalValue;
      alert('Erro ao atualizar status da vaga: ' + error.message);
    } finally {
      this.disabled = false;
      this.style.opacity = '1';
    }
  });
  select.setAttribute('data-original-value', select.value);
});

// Modal de Parecer
const parecerModalOverlay = document.getElementById('parecerModalOverlay');
const parecerCandidateName = document.getElementById('parecerCandidateName');
const parecerLoading = document.getElementById('parecerLoading');
const parecerGenerating = document.getElementById('parecerGenerating');
const parecerError = document.getElementById('parecerError');
const parecerTypeForm = document.getElementById('parecerTypeForm');
const parecerTypeSelect = document.getElementById('parecerTypeSelect');
const parecerExistingHint = document.getElementById('parecerExistingHint');
const parecerExistingType = document.getElementById('parecerExistingType');
const parecerResult = document.getElementById('parecerResult');
const parecerText = document.getElementById('parecerText');
const parecerSolicitarBtn = document.getElementById('parecerSolicitarBtn');
const parecerCopiarBtn = document.getElementById('parecerCopiarBtn');
const parecerNovoBtn = document.getElementById('parecerNovoBtn');
const parecerFecharBtn = document.getElementById('parecerFecharBtn');

let parecerJobId = null;
let parecerCandidateJobId = null;
let parecerPollInterval = null;
let parecerCurrentType = null;

function hideParecerStates() {
  parecerLoading.style.display = 'none';
  parecerGenerating.style.display = 'none';
  parecerError.style.display = 'none';
  parecerTypeForm.style.display = 'none';
  parecerResult.style.display = 'none';
  parecerSolicitarBtn.style.display = 'none';
  parecerCopiarBtn.style.display = 'none';
  parecerNovoBtn.style.display = 'none';
}

function showParecerResult(text, parecerType) {
  hideParecerStates();
  parecerText.textContent = text || '';
  parecerResult.style.display = 'block';
  parecerCopiarBtn.style.display = 'inline-block';
  parecerNovoBtn.style.display = 'inline-block';
  parecerCurrentType = parecerType;
}

function showParecerTypeForm(existingType) {
  hideParecerStates();
  parecerTypeForm.style.display = 'block';
  parecerSolicitarBtn.style.display = 'inline-block';
  if (existingType) {
    parecerExistingHint.style.display = 'block';
    parecerExistingType.textContent = existingType === 'RESUMIDO' ? 'Resumido' : existingType === 'COMPLETO' ? 'Completo' : 'Robusto';
  } else {
    parecerExistingHint.style.display = 'none';
  }
}

function stopParecerPolling() {
  if (parecerPollInterval) {
    clearInterval(parecerPollInterval);
    parecerPollInterval = null;
  }
}

async function fetchParecerStatus() {
  const resp = await fetch(`/vagas/${parecerJobId}/candidatos/${parecerCandidateJobId}/parecer-status/`, { cache: 'no-store' });
  if (!resp.ok) return null;
  return resp.json();
}

function pollParecerStatus() {
  parecerPollInterval = setInterval(async () => {
    const data = await fetchParecerStatus();
    if (!data) return;
    if (data.status === 'completed') {
      stopParecerPolling();
      parecerGenerating.style.display = 'none';
      showParecerResult(data.parecer, data.parecer_type);
    } else if (data.status === 'error') {
      stopParecerPolling();
      parecerGenerating.style.display = 'none';
      parecerError.textContent = data.message || 'Erro ao gerar parecer.';
      parecerError.style.display = 'block';
    }
  }, 2000);
}

document.querySelectorAll('.btn-parecer').forEach(btn => {
  btn.addEventListener('click', async function() {
    parecerJobId = this.getAttribute('data-job-id');
    parecerCandidateJobId = this.getAttribute('data-candidate-job-id');
    parecerCandidateName.textContent = this.getAttribute('data-candidate-name') || 'Candidato';

    hideParecerStates();
    parecerLoading.style.display = 'block';
    parecerModalOverlay.classList.add('active');

    try {
      const data = await fetchParecerStatus();
      parecerLoading.style.display = 'none';
      if (data && data.status === 'completed' && data.parecer) {
        showParecerResult(data.parecer, data.parecer_type);
      } else {
        showParecerTypeForm(data?.parecer_type || null);
      }
    } catch (err) {
      parecerLoading.style.display = 'none';
      showParecerTypeForm(null);
    }
  });
});

if (parecerSolicitarBtn) {
  parecerSolicitarBtn.addEventListener('click', async function() {
    const parecerType = parecerTypeSelect.value;
    const csrftoken = getCSRFToken();
    if (!csrftoken) {
      alert('Token CSRF não encontrado. Recarregue a página.');
      return;
    }
    parecerSolicitarBtn.disabled = true;
    hideParecerStates();
    parecerGenerating.style.display = 'block';

    try {
      const formData = new FormData();
      formData.append('parecer_type', parecerType);
      formData.append('csrfmiddlewaretoken', csrftoken);
      const resp = await fetch(`/vagas/${parecerJobId}/candidatos/${parecerCandidateJobId}/parecer/`, {
        method: 'POST',
        body: formData,
        headers: { 'X-CSRFToken': csrftoken },
        credentials: 'same-origin'
      });
      const data = await resp.json().catch(() => ({}));

      if (!resp.ok) {
        throw new Error(data.error || 'Erro ao solicitar parecer.');
      }

      if (data.status === 'completed') {
        parecerGenerating.style.display = 'none';
        showParecerResult(data.parecer, data.parecer_type);
      } else if (data.status === 'running') {
        pollParecerStatus();
      }
    } catch (err) {
      parecerGenerating.style.display = 'none';
      parecerError.textContent = err.message;
      parecerError.style.display = 'block';
    } finally {
      parecerSolicitarBtn.disabled = false;
    }
  });
}

if (parecerNovoBtn) {
  parecerNovoBtn.addEventListener('click', function() {
    showParecerTypeForm(parecerCurrentType);
  });
}

if (parecerCopiarBtn) {
  parecerCopiarBtn.addEventListener('click', function() {
    const text = parecerText.textContent;
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      const orig = parecerCopiarBtn.textContent;
      parecerCopiarBtn.textContent = 'Copiado!';
      setTimeout(() => { parecerCopiarBtn.textContent = orig; }, 2000);
    }).catch(() => {
      alert('Não foi possível copiar.');
    });
  });
}

if (parecerFecharBtn && parecerModalOverlay) {
  parecerFecharBtn.addEventListener('click', function() {
    stopParecerPolling();
    parecerModalOverlay.classList.remove('active');
  });
  parecerModalOverlay.addEventListener('click', function(e) {
    if (e.target === parecerModalOverlay) {
      stopParecerPolling();
      parecerModalOverlay.classList.remove('active');
    }
  });
}

// Busca no banco de talentos - Sistema de preview
const searchInPoolBtn = document.getElementById('searchInPoolBtn');
const searchFiltersModal = document.getElementById('searchFiltersModal');
const previewCandidatesModal = document.getElementById('previewCandidatesModal');
const cancelSearchFiltersBtn = document.getElementById('cancelSearchFiltersBtn');
const searchFiltersForm = document.getElementById('searchFiltersForm');
const newSearchBtn = document.getElementById('newSearchBtn');
const analyzeAndLinkBtn = document.getElementById('analyzeAndLinkBtn');

let currentMinScore = null;

if (searchInPoolBtn && searchFiltersModal) {
  // Abre modal de filtros ao clicar no botão
  searchInPoolBtn.addEventListener('click', function() {
    searchFiltersModal.style.display = 'flex';
  });
  
  // Fecha modal ao clicar em cancelar ou fora
  if (cancelSearchFiltersBtn) {
    cancelSearchFiltersBtn.addEventListener('click', function() {
      searchFiltersModal.style.display = 'none';
    });
  }
  
  searchFiltersModal.addEventListener('click', function(e) {
    if (e.target === searchFiltersModal) {
      searchFiltersModal.style.display = 'none';
    }
  });
  
  // Botão "Fazer Nova Busca" no preview
  if (newSearchBtn) {
    newSearchBtn.addEventListener('click', function() {
      previewCandidatesModal.style.display = 'none';
      searchFiltersModal.style.display = 'flex';
    });
  }
  
  // Fecha preview ao clicar fora
  if (previewCandidatesModal) {
    previewCandidatesModal.addEventListener('click', function(e) {
      if (e.target === previewCandidatesModal) {
        previewCandidatesModal.style.display = 'none';
      }
    });
  }
  
  // Função para renderizar preview
  function renderPreview(data) {
    const totalEl = document.getElementById('previewTotal');
    const listEl = document.getElementById('previewCandidatesList');
    const paginationEl = document.getElementById('previewPagination');
    
    if (totalEl) {
      totalEl.textContent = `${data.total} candidato(s) com match mínimo de ${data.min_score}%`;
    }

    if (listEl) {
      if (data.candidates.length === 0) {
        listEl.innerHTML = '<p style="color: var(--muted); text-align: center; padding: 20px;">Nenhum candidato do banco atingiu o match mínimo. Tente reduzir o percentual.</p>';
      } else {
        let html = '<table class="table" style="width: 100%; font-size: 13px;"><thead><tr>';
        html += '<th>Nome</th><th>Empresa</th><th>Match</th><th>Requisitos atendidos</th><th>Currículo</th><th>Pronto em</th>';
        html += '</tr></thead><tbody>';

        data.candidates.forEach(candidate => {
          html += '<tr>';
          html += `<td>${candidate.name}</td>`;
          html += `<td>${candidate.company}</td>`;
          html += `<td><strong style="color: var(--primary);">${candidate.match_score}%</strong></td>`;
          html += `<td style="max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${candidate.matched_terms}">${candidate.matched_terms}</td>`;
          html += `<td>${candidate.has_resume ? `<a href="/curriculos/${candidate.id}/">Baixar PDF</a>` : 'Dados cadastrados'}</td>`;
          html += `<td>${candidate.ready_at}</td>`;
          html += '</tr>';
        });

        html += '</tbody></table>';
        listEl.innerHTML = html;
      }
    }
    
    if (paginationEl && data.num_pages > 1) {
      let pagHtml = '';
      if (data.has_previous) {
        pagHtml += `<button class="btn" onclick="loadPreviewPage(${data.page - 1})" style="font-size: 12px;">Anterior</button>`;
      }
      pagHtml += `<span style="margin: 0 10px; color: var(--muted);">Página ${data.page} de ${data.num_pages}</span>`;
      if (data.has_next) {
        pagHtml += `<button class="btn" onclick="loadPreviewPage(${data.page + 1})" style="font-size: 12px;">Próxima</button>`;
      }
      paginationEl.innerHTML = pagHtml;
    } else if (paginationEl) {
      paginationEl.innerHTML = '';
    }
  }
  
  // Função para carregar página do preview
  window.loadPreviewPage = function(page) {
    if (currentMinScore === null) return;

    const jobId = searchInPoolBtn.getAttribute('data-job-id');
    const formData = new FormData();
    const csrftoken = getCSRFToken();

    formData.append('min_score', currentMinScore);
    formData.append('page', page);
    formData.append('csrfmiddlewaretoken', csrftoken);
    
    fetch(`/vagas/${jobId}/preview-search/`, {
      method: 'POST',
      body: formData,
      headers: {
        'X-CSRFToken': csrftoken,
      },
      credentials: 'same-origin'
    })
    .then(resp => resp.json())
    .then(data => {
      if (data.success) {
        renderPreview(data);
      }
    })
    .catch(err => console.error('Erro ao carregar página:', err));
  };
  
  // Submete formulário de busca (preview)
  if (searchFiltersForm) {
    searchFiltersForm.addEventListener('submit', async function(e) {
      e.preventDefault();
      
      const jobId = searchInPoolBtn.getAttribute('data-job-id');
      searchInPoolBtn.disabled = true;
      searchInPoolBtn.style.opacity = '0.6';
      searchInPoolBtn.textContent = 'Buscando...';
      
      try {
        const formData = new FormData(this);
        const csrftoken = getCSRFToken();
        
        if (!csrftoken) {
          throw new Error('Token CSRF não encontrado. Recarregue a página.');
        }
        
        formData.append('csrfmiddlewaretoken', csrftoken);

        // Salva o match mínimo escolhido para paginação e análise
        currentMinScore = formData.get('min_score');

        const response = await fetch(`/vagas/${jobId}/preview-search/`, {
          method: 'POST',
          body: formData,
          headers: {
            'X-CSRFToken': csrftoken,
          },
          credentials: 'same-origin'
        });
        
        const responseData = await response.json().catch(() => ({}));
        
        if (!response.ok) {
          throw new Error(responseData.error || `Erro ${response.status}: ${response.statusText}`);
        }
        
        if (responseData.success) {
          searchFiltersModal.style.display = 'none';
          previewCandidatesModal.style.display = 'flex';
          renderPreview(responseData);
        }
        
      } catch (error) {
        console.error('Erro ao buscar no banco:', error);
        alert('Erro ao buscar no banco: ' + error.message);
      } finally {
        searchInPoolBtn.disabled = false;
        searchInPoolBtn.style.opacity = '1';
        searchInPoolBtn.textContent = 'Buscar no banco';
      }
    });
  }
  
  // Botão "Analisar e Vincular"
  if (analyzeAndLinkBtn) {
    analyzeAndLinkBtn.addEventListener('click', async function() {
      if (currentMinScore === null) {
        alert('Nenhuma busca feita. Informe o match mínimo primeiro.');
        return;
      }

      const jobId = searchInPoolBtn.getAttribute('data-job-id');
      this.disabled = true;
      this.style.opacity = '0.6';
      this.textContent = 'Analisando...';
      previewCandidatesModal.style.display = 'none';

      try {
        const formData = new FormData();
        const csrftoken = getCSRFToken();

        if (!csrftoken) {
          throw new Error('Token CSRF não encontrado. Recarregue a página.');
        }

        formData.append('min_score', currentMinScore);
        formData.append('csrfmiddlewaretoken', csrftoken);
        
        const response = await fetch(`/vagas/${jobId}/search-pool/`, {
          method: 'POST',
          body: formData,
          headers: {
            'X-CSRFToken': csrftoken,
          },
          credentials: 'same-origin'
        });
        
        const responseData = await response.json().catch(() => ({}));
        
        if (!response.ok) {
          throw new Error(responseData.error || `Erro ${response.status}: ${response.statusText}`);
        }
        
        // Inicia polling do status
        const searchStatusEl = document.getElementById('searchStatus');
        if (searchStatusEl) {
          const statusUrl = searchStatusEl.getAttribute('data-status-url');
          const poll = async () => {
            try {
              const resp = await fetch(statusUrl, { cache: 'no-store' });
              if (!resp.ok) { reagendarPoll(poll); return; }
              const data = await resp.json();
              if (data.status === 'running') {
                const total = data.total ?? '?';
                const processed = data.processed ?? 0;
                const errors = data.errors ?? 0;
                let html = `<strong style="color: var(--primary);">Análise em andamento:</strong> ${processed}/${total}`;
                if (errors > 0) {
                  html += ` <span style="color: #d32f2f;">(${errors} erro(s))</span>`;
                }
                html += listaDeErros(data.error_details);
                searchStatusEl.innerHTML = html;
                searchStatusEl.style.color = 'var(--text)';
                setTimeout(poll, 2000);
              } else if (data.status === 'completed') {
                const result = data.result || {};
                const linked = result.linked || 0;
                const errors = result.errors || 0;
                let html = `<strong style="color: var(--primary);">Análise concluída.</strong>`;
                html += `<div style="margin-top: 6px; font-size: 12px; color: var(--muted);">`;
                html += `${linked} candidatos vinculados`;
                if (errors > 0) {
                  html += ` <span style="color: #d32f2f;">, ${errors} erro(s)</span>`;
                }
                html += `</div>`;
                searchStatusEl.innerHTML = html;
                searchStatusEl.style.color = 'var(--text)';
                // Recarrega a página para mostrar os novos candidatos
                setTimeout(() => {
                  window.location.reload();
                }, 2000);
              } else if (data.status === 'error') {
                const message = data.message || 'Erro desconhecido';
                searchStatusEl.innerHTML = `<strong style="color: #d32f2f;">Falha na análise:</strong> ${message}`;
                searchStatusEl.style.color = 'var(--text)';
              }
            } catch (err) {
              reagendarPoll(poll);
            }
          };
          poll();
        }
        
      } catch (error) {
        console.error('Erro ao analisar candidatos:', error);
        alert('Erro ao analisar candidatos: ' + error.message);
      } finally {
        this.disabled = false;
        this.style.opacity = '1';
        this.textContent = 'Analisar e Vincular';
      }
    });
  }
}

// Polling do status da busca (se já estiver rodando)
const searchStatusEl = document.getElementById('searchStatus');
if (searchStatusEl) {
  const statusUrl = searchStatusEl.getAttribute('data-status-url');
  const pollSearch = async () => {
    try {
      const resp = await fetch(statusUrl, { cache: 'no-store' });
      if (!resp.ok) { reagendarPoll(poll); return; }
      const data = await resp.json();
      if (data.status === 'running') {
        const total = data.total ?? '?';
        const processed = data.processed ?? 0;
        const errors = data.errors ?? 0;
        let html = `<strong style="color: var(--primary);">Busca em andamento:</strong> ${processed}/${total}`;
        if (errors > 0) {
          html += ` <span style="color: #d32f2f;">(${errors} erro(s))</span>`;
        }
        searchStatusEl.innerHTML = html;
        searchStatusEl.style.color = 'var(--text)';
        setTimeout(pollSearch, 2000);
      } else if (data.status === 'completed') {
        const result = data.result || {};
        const linked = result.linked || 0;
        const errors = result.errors || 0;
        let html = `<strong style="color: var(--primary);">Busca concluída.</strong>`;
        html += `<div style="margin-top: 6px; font-size: 12px; color: var(--muted);">`;
        html += `${linked} candidatos vinculados`;
        if (errors > 0) {
          html += ` <span style="color: #d32f2f;">, ${errors} erro(s)</span>`;
        }
        html += `</div>`;
        searchStatusEl.innerHTML = html;
        searchStatusEl.style.color = 'var(--text)';
      } else if (data.status === 'error') {
        const message = data.message || 'Erro desconhecido';
        searchStatusEl.innerHTML = `<strong style="color: #d32f2f;">Falha na busca:</strong> ${message}`;
        searchStatusEl.style.color = 'var(--text)';
      }
    } catch (err) {
      reagendarPoll(poll);
    }
  };
  pollSearch();
}
