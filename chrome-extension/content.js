// content.js — Detecta documentos de saúde na página e notifica o popup

(function () {
  // Portais conhecidos e seus seletores de PDF/documento
  const PORTALS = [
    {
      name: 'Resulta / Dasa',
      match: /resulta\.com\.br|diagnosticosdaamerica\.com\.br|dasa\.com\.br/i,
      findLinks: () => [...document.querySelectorAll('a[href*=".pdf"], a[href*="laudo"], a[href*="resultado"], a[href*="exame"]')],
    },
    {
      name: 'Einstein Online',
      match: /einstein\.br/i,
      findLinks: () => [...document.querySelectorAll('a[href*=".pdf"], a[href*="resultado"], a[href*="laudo"], button[data-pdf]')],
    },
    {
      name: 'SMS-Rio / e-SUS',
      match: /smsrio\.org|esus\.saude\.gov\.br|rio\.rj\.gov\.br/i,
      findLinks: () => [...document.querySelectorAll('a[href*=".pdf"], a[href*="documento"], a[href*="prontuario"]')],
    },
  ];

  // Detecta portal atual
  const currentPortal = PORTALS.find(p => p.match.test(location.hostname));

  // Coleta links de documentos
  function getDocumentLinks() {
    const links = [];

    // Portal específico
    if (currentPortal) {
      currentPortal.findLinks().forEach(el => {
        const href = el.href || el.dataset.pdf || '';
        if (href) links.push({ url: href, label: el.textContent.trim() || href, portal: currentPortal.name });
      });
    }

    // Genérico: qualquer link/embed para PDF na página
    document.querySelectorAll('a[href$=".pdf"], embed[src$=".pdf"], iframe[src$=".pdf"]').forEach(el => {
      const url = el.href || el.src || '';
      if (url && !links.find(l => l.url === url)) {
        links.push({ url, label: el.textContent?.trim() || url.split('/').pop(), portal: 'Genérico' });
      }
    });

    // Se a própria página é um PDF
    if (document.contentType === 'application/pdf' || location.pathname.endsWith('.pdf')) {
      links.push({ url: location.href, label: document.title || location.pathname.split('/').pop(), portal: 'PDF direto' });
    }

    return links;
  }

  // Responde ao popup
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === 'SCAN_PAGE') {
      sendResponse({
        portal: currentPortal?.name || null,
        pageTitle: document.title,
        pageUrl: location.href,
        links: getDocumentLinks(),
      });
    }
    if (msg.type === 'FETCH_PDF') {
      // Baixa o PDF como base64 para enviar via background
      fetch(msg.url, { credentials: 'include' })
        .then(r => r.blob())
        .then(blob => {
          const reader = new FileReader();
          reader.onload = () => sendResponse({ ok: true, dataUrl: reader.result, filename: msg.url.split('/').pop().split('?')[0] || 'documento.pdf' });
          reader.readAsDataURL(blob);
        })
        .catch(err => sendResponse({ ok: false, error: err.message }));
      return true; // async
    }
  });
})();
