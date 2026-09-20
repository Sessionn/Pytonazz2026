/* Enhance the native POST only when the required browser APIs exist.
 * Authentication and rate limiting remain entirely on the server. */
(() => {
  const form=document.querySelector('.login-page form');
  if(!form || !window.fetch || !window.DOMParser) return;
  let pending=false;
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(pending) return;
    pending=true;
    const button=form.querySelector('[type="submit"]');
    button.disabled=true;form.setAttribute('aria-busy','true');
    function error(message) {
      let alert=document.querySelector('.login-error');
      if(!alert){alert=document.createElement('div');alert.className='login-error';alert.setAttribute('role','alert');form.before(alert);}
      alert.textContent=message;
    }
    try {
      const response=await fetch(form.action,{method:'POST',body:new FormData(form),credentials:'same-origin'});
      const next=new DOMParser().parseFromString(await response.text(),'text/html');
      const destination=new URL(response.url);
      if(!response.ok || !response.redirected || !next.body.classList.contains('library-page')) {
        error(next.querySelector('.login-error')?.textContent || 'Accesso non riuscito. Riprova.');return;
      }
      if(destination.origin!==location.origin) throw new Error('Invalid destination');
      const canvas=document.querySelector('.python-overlay');
      // Execute only known local entry points, never scripts parsed from HTML.
      next.querySelectorAll('script').forEach(script=>script.remove());
      const old=document.querySelector('.login-wrap');
      const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
      if(!reduced && old.animate) await old.animate([{opacity:1},{opacity:0,transform:'translateY(-10px)'}],
        {duration:220,easing:'ease-in',fill:'forwards'}).finished;
      document.body.replaceChildren(...next.body.childNodes);
      document.body.className='library-page dashboard-entering';
      if(canvas) document.body.append(canvas);
      document.title=next.title;
      history.replaceState(null,'',destination.pathname+destination.search);
      document.dispatchEvent(new Event('pytonazz:dashboard'));
      for(const name of ['pagination.js','dashboard.js']) {
        await new Promise((resolve,reject)=>{
          const script=document.createElement('script');script.src='/static/js/'+name;
          script.onload=resolve;script.onerror=reject;document.body.append(script);
        });
      }
      document.getElementById('main-content')?.focus({preventScroll:true});
    } catch (_) {
      // A successful login followed by an asset error can use the native page.
      if(document.body.classList.contains('library-page')) location.replace('/');
      else error('Connessione non disponibile. Riprova quando torna online.');
    } finally {pending=false;button.disabled=false;form.removeAttribute('aria-busy');}
  });
})();
