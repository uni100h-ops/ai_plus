(()=>{'use strict';
const form=document.getElementById('loginForm'),button=document.getElementById('signIn'),error=document.getElementById('loginError'),password=document.getElementById('password');
form.addEventListener('submit',async event=>{
 event.preventDefault();button.disabled=true;error.hidden=true;
 try{
  const response=await fetch('/api/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Metaquant-Request':'1'},body:JSON.stringify({password:password.value})});
  password.value='';
  if(!response.ok)throw new Error(response.status===429?'Too many attempts. Wait one minute and try again.':response.status===401?'Incorrect password.':'Sign-in failed. Please try again.');
  location.replace('/');
 }catch(e){password.value='';error.textContent=e.message;error.hidden=false;button.disabled=false;password.focus();}
});
})();
