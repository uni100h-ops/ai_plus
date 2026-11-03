'use strict';
(() => {
  const el = id => document.getElementById(id);
  let template = null;
  let info = null;
  const ps = value => "'" + value.replaceAll("'", "''") + "'";
  function makeScript() {
    if (!template) return;
    const numerical = el('apiExample').value === 'optimization';
    const payload = numerical
      ? "@{ spec = @{ kind = 'channels'; size = 16; seed = 20261026; variant = 'standard' } }"
      : "@{ question = 'What is the capital of France?' }";
    el('apiScript').textContent = template
      .replace("'__SERVICE_URL__'", ps(location.origin))
      .replace("'__OPERATION__'", ps(el('apiOperation').value))
      .replace('__PAYLOAD__', payload);
    el('apiCopy').disabled = false;
    el('apiDownload').disabled = false;
  }
  async function loadGuide() {
    if (template && info) return;
    el('apiStatus').textContent = 'Checking API configuration…';
    try {
      const responses = await Promise.all([
        fetch('/api/service-info', {credentials:'same-origin'}),
        fetch('/api-client.ps1', {credentials:'same-origin'})
      ]);
      if (responses.some(r => r.status === 401 || r.redirected)) {
        el('apiStatus').textContent = 'Your session expired. Sign in again.'; return;
      }
      if (responses.some(r => !r.ok)) throw Error('Unable to load API guide.');
      info = await responses[0].json(); template = await responses[1].text();
      el('apiStatus').textContent = info.api_status === 'enabled'
        ? 'API enabled · ' + (info.model?.label || 'Check model configuration')
        : 'Setup required: add a random AI_PLUS_API_KEY (32–256 characters) in Render → Environment, then deploy.';
      if (info.api_status === 'enabled' && !info.meta_configured)
        el('apiStatus').textContent += ' · API configuration is missing.';
      if (info.api_status === 'enabled' && !info.optimizer_available)
        el('apiStatus').textContent += ' · Optimizer unavailable: numerical requests need Modal credentials.';
      makeScript();
    } catch {
      el('apiStatus').textContent = 'Unable to load the guide. Close this window and try again.';
      info = null;
    }
  }
  el('apiAccess').onclick = () => { el('apiDialog').showModal(); loadGuide(); };
  el('apiOperation').onchange = makeScript;
  el('apiExample').onchange = makeScript;
  el('apiCopy').onclick = async () => {
    try {
      await navigator.clipboard.writeText(el('apiScript').textContent);
      el('apiCopyStatus').textContent = 'Copied. Paste into PowerShell to call the deployed API.';
    } catch {
      const range = document.createRange(); range.selectNodeContents(el('apiScript'));
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
      el('apiCopyStatus').textContent = 'Press Ctrl+C to copy the selected script.';
    }
  };
  el('apiDownload').onclick = () => {
    const blob = new Blob([el('apiScript').textContent], {type:'text/plain;charset=utf-8'});
    const url = URL.createObjectURL(blob); const a = document.createElement('a');
    a.href = url; a.download = 'CALL_META_AI_PLUS.ps1'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
})();
