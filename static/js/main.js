/* ==========================================================
   MeuDocMed — JavaScript Principal
   ========================================================== */

document.addEventListener('DOMContentLoaded', function () {

  // ----------------------------------------------------------
  // Toggle de visibilidade da senha
  // ----------------------------------------------------------
  document.querySelectorAll('.toggle-pw').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const input = this.parentElement.querySelector('input[type="password"], input[type="text"]');
      if (!input) return;
      const isPassword = input.type === 'password';
      input.type = isPassword ? 'text' : 'password';
      const icon = this.querySelector('i');
      if (icon) {
        icon.className = isPassword ? 'fa fa-eye-slash' : 'fa fa-eye';
      }
    });
  });

  // ----------------------------------------------------------
  // Máscara de CPF
  // ----------------------------------------------------------
  document.querySelectorAll('input#cpf, input[name="cpf"]').forEach(function (input) {
    input.addEventListener('input', function () {
      let v = this.value.replace(/\D/g, '').slice(0, 11);
      if (v.length > 9)      v = v.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, '$1.$2.$3-$4');
      else if (v.length > 6) v = v.replace(/(\d{3})(\d{3})(\d+)/, '$1.$2.$3');
      else if (v.length > 3) v = v.replace(/(\d{3})(\d+)/, '$1.$2');
      this.value = v;
    });
  });

  // ----------------------------------------------------------
  // Máscara de telefone
  // ----------------------------------------------------------
  document.querySelectorAll('input[type="tel"]').forEach(function (input) {
    input.addEventListener('input', function () {
      let v = this.value.replace(/\D/g, '').slice(0, 11);
      if (v.length > 10) v = v.replace(/(\d{2})(\d{5})(\d{4})/, '($1) $2-$3');
      else if (v.length > 6) v = v.replace(/(\d{2})(\d{4})(\d+)/, '($1) $2-$3');
      else if (v.length > 2) v = v.replace(/(\d{2})(\d+)/, '($1) $2');
      this.value = v;
    });
  });

  // ----------------------------------------------------------
  // Sidebar toggle (mobile)
  // ----------------------------------------------------------
  window.toggleSidebar = function () {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    if (!sidebar) return;
    sidebar.classList.toggle('open');
    if (overlay) overlay.classList.toggle('show');
  };

  // ----------------------------------------------------------
  // Auto-fechar alerts depois de 6 segundos
  // ----------------------------------------------------------
  document.querySelectorAll('.alert').forEach(function (alert) {
    setTimeout(function () {
      if (alert.parentElement) {
        alert.style.transition = 'opacity .4s';
        alert.style.opacity = '0';
        setTimeout(function () { alert.remove(); }, 400);
      }
    }, 6000);
  });

  // ----------------------------------------------------------
  // Formulários: desabilitar botão de submit após clique
  // para evitar duplo envio (exceto upload, que faz no template)
  // ----------------------------------------------------------
  document.querySelectorAll('form:not(#upload-form)').forEach(function (form) {
    form.addEventListener('submit', function () {
      const btn = form.querySelector('[type="submit"]');
      if (btn && !btn.dataset.noDisable) {
        setTimeout(function () {
          btn.disabled = true;
        }, 50);
      }
    });
  });

  // ----------------------------------------------------------
  // Confirmação inline de formulários de exclusão simples
  // (para casos onde não há modal customizado)
  // ----------------------------------------------------------
  document.querySelectorAll('[data-confirm]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      if (!confirm(this.dataset.confirm)) {
        e.preventDefault();
      }
    });
  });

  // ----------------------------------------------------------
  // Copiar para a área de transferência (fallback)
  // ----------------------------------------------------------
  window.copyToClipboard = function (text) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
  };

  // ----------------------------------------------------------
  // Validação de CPF no lado cliente (feedback imediato)
  // ----------------------------------------------------------
  function validateCpfDigits(cpf) {
    cpf = cpf.replace(/\D/g, '');
    if (cpf.length !== 11) return false;
    if (/^(\d)\1+$/.test(cpf)) return false;
    let sum = 0;
    for (let i = 0; i < 9; i++) sum += parseInt(cpf[i]) * (10 - i);
    let r = (sum * 10) % 11;
    if (r === 10 || r === 11) r = 0;
    if (r !== parseInt(cpf[9])) return false;
    sum = 0;
    for (let i = 0; i < 10; i++) sum += parseInt(cpf[i]) * (11 - i);
    r = (sum * 10) % 11;
    if (r === 10 || r === 11) r = 0;
    return r === parseInt(cpf[10]);
  }

  document.querySelectorAll('input#cpf, input[name="cpf"]').forEach(function (input) {
    input.addEventListener('blur', function () {
      const cpf = this.value.replace(/\D/g, '');
      if (cpf.length === 11) {
        if (!validateCpfDigits(cpf)) {
          this.style.borderColor = 'var(--danger)';
          let hint = this.parentElement.querySelector('.cpf-error');
          if (!hint) {
            hint = document.createElement('small');
            hint.className = 'cpf-error form-hint';
            hint.style.color = 'var(--danger)';
            hint.textContent = 'CPF inválido. Verifique os dígitos.';
            this.parentElement.appendChild(hint);
          }
        } else {
          this.style.borderColor = 'var(--success)';
          const hint = this.parentElement.querySelector('.cpf-error');
          if (hint) hint.remove();
        }
      }
    });
    input.addEventListener('focus', function () {
      this.style.borderColor = '';
      const hint = this.parentElement.querySelector('.cpf-error');
      if (hint) hint.remove();
    });
  });

  // ----------------------------------------------------------
  // Confirmação de senha (feedback imediato)
  // ----------------------------------------------------------
  const pw2Fields = document.querySelectorAll(
    'input[name="password2"], input[name="new_password2"]'
  );
  pw2Fields.forEach(function (pw2) {
    pw2.addEventListener('input', function () {
      const name = this.name === 'password2' ? 'password' : 'new_password';
      const pw1 = document.querySelector(`input[name="${name}"]`);
      if (!pw1) return;
      if (this.value && pw1.value !== this.value) {
        this.style.borderColor = 'var(--danger)';
      } else {
        this.style.borderColor = pw1.value === this.value ? 'var(--success)' : '';
      }
    });
  });

  // ----------------------------------------------------------
  // Destaca linha da tabela ao passar o mouse
  // (já feito via CSS, mas adiciona marcação via JS para
  //  acessibilidade extra)
  // ----------------------------------------------------------
  document.querySelectorAll('table.table tbody tr').forEach(function (tr) {
    tr.setAttribute('tabindex', '0');
  });

});
