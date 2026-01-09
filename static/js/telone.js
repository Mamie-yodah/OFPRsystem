document.addEventListener('DOMContentLoaded', function(){
  // If a QR container exists, create a QR code from data-qrcode attribute or fallback sample
  document.querySelectorAll('[data-qrcode]').forEach(function(el){
    const data = el.getAttribute('data-qrcode') || 'telone-sandbox://invoice/0001';
    try{
      QRCode.toCanvas(el, data, {width:200}).catch(console.error);
    }catch(e){
      // fallback for environments where QRCode lib not loaded
      el.textContent = 'QR Ready - '+data;
    }
  });

  // Simulate payment confirmation: buttons with data-sim-pay target a form
  document.querySelectorAll('[data-sim-pay]').forEach(function(btn){
    btn.addEventListener('click', function(e){
      e.preventDefault();
      const confirmButton = btn;
      confirmButton.disabled = true;
      confirmButton.textContent = 'Processing...';
      setTimeout(function(){
        // Create an invisible form post to simulate server side update if route exists
        const form = document.createElement('form');
        form.method = 'post';
        form.style.display = 'none';
        // include a field to indicate simulated payment
        const input = document.createElement('input');
        input.name = 'simulated_payment';
        input.value = '1';
        form.appendChild(input);
        document.body.appendChild(form);
        // submit if action specified on button via data-action
        const action = btn.getAttribute('data-action');
        if(action){
          form.action = action;
          form.submit();
        } else {
          // show a success toast
          alert('Payment simulated successfully (client-side). You can now click Confirm on the site.');
          confirmButton.disabled = false;
          confirmButton.textContent = 'Confirm Payment';
        }
      }, 1200);
    });
  });
});