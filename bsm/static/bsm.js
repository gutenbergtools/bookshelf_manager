document.addEventListener('change',e=>{if(e.target.matches('select[data-autosubmit]'))e.target.form.submit()});
document.addEventListener('click',e=>{var b=e.target.closest('[data-confirm]');if(b&&!window.confirm(b.getAttribute('data-confirm')))e.preventDefault()});
document.addEventListener('submit',()=>sessionStorage.setItem('bsm:scroll',JSON.stringify({y:scrollY,path:location.pathname})));
window.addEventListener('load',()=>{var v=sessionStorage.getItem('bsm:scroll');if(!v)return;sessionStorage.removeItem('bsm:scroll');try{v=JSON.parse(v);if(v.path===location.pathname)scrollTo(0,v.y)}catch(e){}});
