let scriptPromise = null;

function loadRazorpayScript() {
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    if (window.Razorpay) {
      resolve(window.Razorpay);
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    script.onload = () => resolve(window.Razorpay);
    script.onerror = () => reject(new Error("Could not load Razorpay Checkout script."));
    document.body.appendChild(script);
  });
  return scriptPromise;
}

/**
 * Opens Razorpay's real Test Mode checkout for the given order.
 * Resolves with the {razorpay_order_id, razorpay_payment_id, razorpay_signature}
 * Razorpay hands back on success. Rejects if the user dismisses the modal
 * or the script fails to load.
 */
export async function openRazorpayCheckout({ orderId, amount, currency, keyId, name, description }) {
  const Razorpay = await loadRazorpayScript();

  return new Promise((resolve, reject) => {
    const rzp = new Razorpay({
      key: keyId,
      order_id: orderId,
      amount,
      currency,
      name: name || "Chargeback Responder Demo",
      description: description || "Test Mode purchase",
      handler: (response) => resolve(response),
      modal: {
        ondismiss: () => reject(new Error("Checkout was closed before completing payment.")),
      },
      theme: { color: "#146356" },
    });
    rzp.on("payment.failed", (resp) => {
      reject(new Error(resp?.error?.description || "Payment failed."));
    });
    rzp.open();
  });
}
