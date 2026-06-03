// background.js — Service Worker da extensão MeuDocMed

const API_BASE = 'https://meudocmed.onrender.com';

// Recebe mensagens do popup e content script
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'UPLOAD_FILE') {
    uploadFile(msg.payload).then(sendResponse).catch(err => sendResponse({ ok: false, error: err.message }));
    return true; // async
  }
  if (msg.type === 'GET_TOKEN') {
    chrome.storage.local.get('mdm_token', data => sendResponse({ token: data.mdm_token || null }));
    return true;
  }
  if (msg.type === 'SET_TOKEN') {
    chrome.storage.local.set({ mdm_token: msg.token }, () => sendResponse({ ok: true }));
    return true;
  }
  if (msg.type === 'CLEAR_TOKEN') {
    chrome.storage.local.remove('mdm_token', () => sendResponse({ ok: true }));
    return true;
  }
});

async function uploadFile({ fileDataUrl, filename, name, category, observation, sourceUrl }) {
  const data = await chrome.storage.local.get('mdm_token');
  const token = data.mdm_token;
  if (!token) throw new Error('Token não configurado. Acesse o MeuDocMed e gere um token.');

  // Converte data URL para Blob
  const resp = await fetch(fileDataUrl);
  const blob = await resp.blob();

  const form = new FormData();
  form.append('file', blob, filename);
  form.append('name', name || filename);
  form.append('category', category || 'outro');
  form.append('observation', observation || '');
  form.append('source_url', sourceUrl || '');

  const r = await fetch(`${API_BASE}/paciente/api/ext/upload`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}` },
    body: form,
  });

  const json = await r.json();
  if (!r.ok) throw new Error(json.error || 'Erro desconhecido');
  return json;
}
