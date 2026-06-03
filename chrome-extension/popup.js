const API_BASE = 'https://meudocmed.onrender.com';

let selectedDocUrl = null;
let selectedDocFilename = null;
let pageLinks = [];

// --- Inicialização ---
document.addEventListener('DOMContentLoaded', async () => {
  const token = await getToken();
  if (token) {
    showMain();
    await loadCategories();
    await scanPage();
  } else {
    show('no-token');
  }

  // Eventos de configuração de token
  document.getElementById('btn-open-mdm').onclick = () =>
    chrome.tabs.create({ url: `${API_BASE}/paciente/perfil` });

  document.getElementById('btn-enter-token').onclick = () => {
    hide('no-token');
    show('token-setup');
  };

  document.getElementById('btn-cancel-token').onclick = () => {
    hide('token-setup');
    show('no-token');
  };

  document.getElementById('btn-save-token').onclick = async () => {
    const val = document.getElementById('token-input').value.trim();
    if (!val) return;
    await setToken(val);
    hide('token-setup');
    showMain();
    await loadCategories();
    await scanPage();
  };

  document.getElementById('btn-reset-token').onclick = async () => {
    await clearToken();
    hide('main');
    show('no-token');
  };

  document.getElementById('file-input').onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    selectedDocUrl = null;
    selectedDocFilename = file.name;
    if (!document.getElementById('doc-name').value)
      document.getElementById('doc-name').value = file.name.replace(/\.[^.]+$/, '');
    document.getElementById('selected-info').style.display = 'block';
    document.getElementById('selected-info').textContent = `Arquivo selecionado: ${file.name}`;
  };

  document.getElementById('btn-send').onclick = sendDocument;
});

// --- Funções de token ---
function getToken() {
  return new Promise(resolve =>
    chrome.runtime.sendMessage({ type: 'GET_TOKEN' }, r => resolve(r?.token || null))
  );
}
function setToken(token) {
  return new Promise(resolve =>
    chrome.runtime.sendMessage({ type: 'SET_TOKEN', token }, resolve)
  );
}
function clearToken() {
  return new Promise(resolve =>
    chrome.runtime.sendMessage({ type: 'CLEAR_TOKEN' }, resolve)
  );
}

// --- UI helpers ---
function show(id) { document.getElementById(id).style.display = ''; }
function hide(id) { document.getElementById(id).style.display = 'none'; }

function showMain() {
  hide('no-token'); hide('token-setup');
  show('main');
}

function showAlert(msg, type = 'info') {
  const area = document.getElementById('alert-area');
  area.innerHTML = `<div class="alert alert-${type}">${msg}</div>`;
  setTimeout(() => { area.innerHTML = ''; }, 5000);
}

// --- Carrega categorias da API ---
async function loadCategories() {
  try {
    const r = await fetch(`${API_BASE}/paciente/api/ext/categories`);
    if (!r.ok) return;
    const cats = await r.json();
    const sel = document.getElementById('doc-category');
    sel.innerHTML = cats.map(c => `<option value="${c.key}">${c.label}</option>`).join('');
  } catch (e) {
    console.warn('Não foi possível carregar categorias:', e);
  }
}

// --- Escaneia a página atual ---
async function scanPage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;

  try {
    const result = await chrome.tabs.sendMessage(tab.id, { type: 'SCAN_PAGE' });
    if (!result) return;

    if (result.portal) {
      const tag = document.getElementById('portal-tag');
      tag.textContent = `Portal detectado: ${result.portal}`;
      tag.style.display = 'block';
    }

    pageLinks = result.links || [];

    if (pageLinks.length > 0) {
      show('doc-list-area');
      hide('no-docs');
      const list = document.getElementById('doc-list');
      list.innerHTML = pageLinks.map((l, i) =>
        `<li class="doc-item" data-idx="${i}">
          <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${l.url}">${l.label || l.url}</span>
          <span class="doc-badge">${l.portal}</span>
        </li>`
      ).join('');

      list.querySelectorAll('.doc-item').forEach(el => {
        el.onclick = () => {
          list.querySelectorAll('.doc-item').forEach(x => x.classList.remove('selected'));
          el.classList.add('selected');
          const link = pageLinks[+el.dataset.idx];
          selectedDocUrl = link.url;
          selectedDocFilename = link.url.split('/').pop().split('?')[0] || 'documento.pdf';
          document.getElementById('file-input').value = '';
          if (!document.getElementById('doc-name').value)
            document.getElementById('doc-name').value = link.label || selectedDocFilename;
          document.getElementById('selected-info').style.display = 'block';
          document.getElementById('selected-info').textContent = `Selecionado: ${link.label || selectedDocFilename}`;
        };
      });
    } else {
      hide('doc-list-area');
      show('no-docs');
    }

    // Página é PDF diretamente
    if (tab.url?.endsWith('.pdf') || tab.url?.includes('application/pdf')) {
      selectedDocUrl = tab.url;
      selectedDocFilename = tab.url.split('/').pop().split('?')[0] || 'documento.pdf';
      document.getElementById('doc-name').value = tab.title || selectedDocFilename;
    }
  } catch (e) {
    hide('doc-list-area');
    show('no-docs');
  }
}

// --- Envia documento ---
async function sendDocument() {
  const name     = document.getElementById('doc-name').value.trim();
  const category = document.getElementById('doc-category').value;
  const obs      = document.getElementById('doc-obs').value.trim();
  const fileInput = document.getElementById('file-input');
  const [tab]    = await chrome.tabs.query({ active: true, currentWindow: true });

  const btn   = document.getElementById('btn-send');
  const label = document.getElementById('btn-send-label');
  btn.disabled = true;
  label.innerHTML = '<span class="spinner"></span> Enviando...';

  try {
    let fileDataUrl, filename;

    if (fileInput.files[0]) {
      // Arquivo selecionado manualmente
      const file = fileInput.files[0];
      filename = file.name;
      fileDataUrl = await new Promise((res, rej) => {
        const fr = new FileReader();
        fr.onload = () => res(fr.result);
        fr.onerror = rej;
        fr.readAsDataURL(file);
      });
    } else if (selectedDocUrl) {
      // Documento da página — pede ao content script para baixar
      const result = await chrome.tabs.sendMessage(tab.id, {
        type: 'FETCH_PDF', url: selectedDocUrl
      });
      if (!result?.ok) throw new Error(result?.error || 'Não foi possível baixar o documento.');
      fileDataUrl = result.dataUrl;
      filename    = result.filename || selectedDocFilename;
    } else {
      showAlert('Selecione um documento na lista ou escolha um arquivo.', 'error');
      return;
    }

    const response = await chrome.runtime.sendMessage({
      type: 'UPLOAD_FILE',
      payload: { fileDataUrl, filename, name: name || filename, category, observation: obs, sourceUrl: tab?.url || '' },
    });

    if (response?.ok) {
      showAlert(`Documento "${response.name}" enviado com sucesso!`, 'success');
      document.getElementById('doc-name').value = '';
      document.getElementById('doc-obs').value = '';
      fileInput.value = '';
      selectedDocUrl = null;
      document.getElementById('selected-info').style.display = 'none';
      document.querySelectorAll('.doc-item').forEach(x => x.classList.remove('selected'));
    } else {
      throw new Error(response?.error || 'Erro desconhecido');
    }
  } catch (e) {
    showAlert(`Erro: ${e.message}`, 'error');
  } finally {
    btn.disabled = false;
    label.textContent = 'Enviar para MeuDocMed';
  }
}
