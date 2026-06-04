const API_BASE = 'https://meudocmed.onrender.com';
let selectedDocUrl = null;
let selectedDocFilename = null;
let pageLinks = [];

// UI helpers
function show(id) { const el = document.getElementById(id); if (el) el.style.display = ''; }
function hide(id) { const el = document.getElementById(id); if (el) el.style.display = 'none'; }

function showAlert(msg, type = 'info') {
  const area = document.getElementById('alert-area');
  if (!area) return;
  area.innerHTML = `<div class="alert alert-${type}">${msg}</div>`;
  setTimeout(() => { area.innerHTML = ''; }, 5000);
}

// Token storage
async function getToken() {
  return new Promise(resolve => {
    try {
      chrome.storage.local.get('mdm_token', d => {
        resolve((d && d.mdm_token) ? d.mdm_token : null);
      });
    } catch(e) { resolve(null); }
  });
}
async function setToken(t) {
  return new Promise(resolve => {
    try { chrome.storage.local.set({ mdm_token: t }, resolve); }
    catch(e) { resolve(); }
  });
}
async function clearToken() {
  return new Promise(resolve => {
    try { chrome.storage.local.remove('mdm_token', resolve); }
    catch(e) { resolve(); }
  });
}

// Init
document.addEventListener('DOMContentLoaded', async () => {
  try {
    const token = await getToken();
    if (token) {
      hide('no-token');
      show('main');
      loadCategories();
      scanPage();
    }
    // se não tem token, no-token já está visível por padrão
  } catch(e) {
    console.error('Init error:', e);
  }

  document.getElementById('btn-open-mdm')?.addEventListener('click', () =>
    chrome.tabs.create({ url: `${API_BASE}/paciente/perfil` })
  );
  document.getElementById('btn-enter-token')?.addEventListener('click', () => {
    hide('no-token'); show('token-setup');
  });
  document.getElementById('btn-cancel-token')?.addEventListener('click', () => {
    hide('token-setup'); show('no-token');
  });
  document.getElementById('btn-save-token')?.addEventListener('click', async () => {
    const val = document.getElementById('token-input')?.value.trim();
    if (!val) return;
    await setToken(val);
    hide('token-setup'); hide('no-token');
    show('main');
    loadCategories();
    scanPage();
  });
  document.getElementById('btn-reset-token')?.addEventListener('click', async () => {
    await clearToken();
    hide('main'); show('no-token');
  });
  document.getElementById('file-input')?.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    selectedDocUrl = null;
    selectedDocFilename = file.name;
    const nameEl = document.getElementById('doc-name');
    if (nameEl && !nameEl.value) nameEl.value = file.name.replace(/\.[^.]+$/, '');
    const info = document.getElementById('selected-info');
    if (info) { info.style.display = 'block'; info.textContent = `Arquivo: ${file.name}`; }
  });
  document.getElementById('btn-send')?.addEventListener('click', sendDocument);
});

async function loadCategories() {
  try {
    const r = await fetch(`${API_BASE}/paciente/api/ext/categories`);
    if (!r.ok) return;
    const cats = await r.json();
    const sel = document.getElementById('doc-category');
    if (sel) sel.innerHTML = cats.map(c => `<option value="${c.key}">${c.label}</option>`).join('');
  } catch(e) {}
}

async function scanPage() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) return;

    let result = null;
    try {
      result = await new Promise((res, rej) => {
        chrome.tabs.sendMessage(tab.id, { type: 'SCAN_PAGE' }, r => {
          if (chrome.runtime.lastError) rej(chrome.runtime.lastError);
          else res(r);
        });
      });
    } catch(e) {}

    pageLinks = result?.links || [];

    if (!pageLinks.length && tab.url?.includes('.pdf')) {
      pageLinks = [{ url: tab.url, label: tab.title || 'documento.pdf', portal: 'PDF direto' }];
    }

    if (result?.portal) {
      const tag = document.getElementById('portal-tag');
      if (tag) { tag.textContent = `Portal: ${result.portal}`; tag.style.display = 'block'; }
    }

    const listArea = document.getElementById('doc-list-area');
    const noDocs = document.getElementById('no-docs');
    const list = document.getElementById('doc-list');

    if (pageLinks.length > 0 && list) {
      if (listArea) listArea.style.display = '';
      if (noDocs) noDocs.style.display = 'none';
      list.innerHTML = pageLinks.map((l, i) =>
        `<li class="doc-item" data-idx="${i}">
          <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${l.label || l.url}</span>
          <span class="doc-badge">${l.portal}</span>
        </li>`
      ).join('');
      list.querySelectorAll('.doc-item').forEach(el => {
        el.addEventListener('click', () => {
          list.querySelectorAll('.doc-item').forEach(x => x.classList.remove('selected'));
          el.classList.add('selected');
          const link = pageLinks[+el.dataset.idx];
          selectedDocUrl = link.url;
          selectedDocFilename = link.url.split('/').pop().split('?')[0] || 'documento.pdf';
          const fi = document.getElementById('file-input');
          if (fi) fi.value = '';
          const nameEl = document.getElementById('doc-name');
          if (nameEl && !nameEl.value) nameEl.value = link.label || selectedDocFilename;
          const info = document.getElementById('selected-info');
          if (info) { info.style.display = 'block'; info.textContent = `Selecionado: ${link.label || selectedDocFilename}`; }
        });
      });
    } else {
      if (listArea) listArea.style.display = 'none';
      if (noDocs) noDocs.style.display = '';
    }
  } catch(e) {
    const noDocs = document.getElementById('no-docs');
    if (noDocs) noDocs.style.display = '';
  }
}

async function sendDocument() {
  const token = await getToken();
  if (!token) { showAlert('Token não configurado.', 'error'); return; }

  const name     = document.getElementById('doc-name')?.value.trim() || '';
  const category = document.getElementById('doc-category')?.value || 'outro';
  const obs      = document.getElementById('doc-obs')?.value.trim() || '';
  const fileInput = document.getElementById('file-input');
  const btn      = document.getElementById('btn-send');
  const label    = document.getElementById('btn-send-label');
  const [tab]    = await chrome.tabs.query({ active: true, currentWindow: true });

  if (btn) btn.disabled = true;
  if (label) label.innerHTML = '<span class="spinner"></span> Enviando...';

  try {
    let blob, filename;

    if (fileInput?.files[0]) {
      blob = fileInput.files[0];
      filename = blob.name;
    } else if (selectedDocUrl) {
      let fetched = null;
      try {
        fetched = await new Promise((res, rej) => {
          chrome.tabs.sendMessage(tab.id, { type: 'FETCH_PDF', url: selectedDocUrl }, r => {
            if (chrome.runtime.lastError) rej(chrome.runtime.lastError);
            else res(r);
          });
        });
      } catch(e) {}

      if (fetched?.ok) {
        const r = await fetch(fetched.dataUrl);
        blob = await r.blob();
        filename = fetched.filename || selectedDocFilename;
      } else {
        const r = await fetch(selectedDocUrl);
        blob = await r.blob();
        filename = selectedDocUrl.split('/').pop().split('?')[0] || 'documento.pdf';
      }
    } else {
      showAlert('Selecione um documento ou arquivo.', 'error');
      return;
    }

    const form = new FormData();
    form.append('file', blob, filename);
    form.append('name', name || filename);
    form.append('category', category);
    form.append('observation', obs);
    form.append('source_url', tab?.url || '');

    const resp = await fetch(`${API_BASE}/paciente/api/ext/upload`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: form,
    });
    const json = await resp.json();

    if (resp.ok && json.ok) {
      showAlert(`"${json.name}" enviado!`, 'success');
      if (document.getElementById('doc-name')) document.getElementById('doc-name').value = '';
      if (document.getElementById('doc-obs'))  document.getElementById('doc-obs').value  = '';
      if (fileInput) fileInput.value = '';
      selectedDocUrl = null;
      const info = document.getElementById('selected-info');
      if (info) info.style.display = 'none';
      document.querySelectorAll('.doc-item').forEach(x => x.classList.remove('selected'));
    } else {
      throw new Error(json.error || 'Erro desconhecido');
    }
  } catch(e) {
    showAlert(`Erro: ${e.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
    if (label) label.textContent = 'Enviar para MeuDocMed';
  }
}
