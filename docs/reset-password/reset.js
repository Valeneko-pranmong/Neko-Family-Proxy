(() => {
  "use strict";

  const states = {
    loading: document.getElementById("state-loading"),
    invalid: document.getElementById("state-invalid"),
    form: document.getElementById("state-form"),
    success: document.getElementById("state-success"),
  };
  const form = document.getElementById("reset-form");
  const password = document.getElementById("password");
  const confirmation = document.getElementById("password-confirm");
  const submitButton = document.getElementById("submit-button");
  const formMessage = document.getElementById("form-message");

  const showState = (name) => {
    Object.values(states).forEach((element) => {
      element.classList.add("hidden");
    });
    states[name].classList.remove("hidden");
  };

  const showFormError = (message) => {
    formMessage.textContent = message;
    formMessage.className = "message error";
  };

  const clearSensitiveUrl = () => {
    window.history.replaceState(
      {},
      document.title,
      window.location.pathname,
    );
  };

  const config = window.NEKO_RESET_CONFIG;
  if (
    !config?.supabaseUrl ||
    !config?.publishableKey ||
    !window.supabase?.createClient
  ) {
    showState("invalid");
    return;
  }

  const client = window.supabase.createClient(
    config.supabaseUrl,
    config.publishableKey,
    {
      auth: {
        autoRefreshToken: false,
        persistSession: false,
        detectSessionInUrl: true,
      },
    },
  );

  let recoverySessionReady = false;
  const acceptRecoverySession = (session) => {
    if (!session || recoverySessionReady) {
      return;
    }
    recoverySessionReady = true;
    clearSensitiveUrl();
    showState("form");
    password.focus();
  };

  client.auth.onAuthStateChange((event, session) => {
    if (event === "PASSWORD_RECOVERY" || event === "SIGNED_IN") {
      acceptRecoverySession(session);
    }
  });

  const initialize = async () => {
    const hash = new URLSearchParams(window.location.hash.slice(1));
    const query = new URLSearchParams(window.location.search);
    if (hash.get("error") || hash.get("error_code")) {
      clearSensitiveUrl();
      showState("invalid");
      return;
    }

    try {
      const code = query.get("code");
      if (code) {
        const { data, error } = await client.auth.exchangeCodeForSession(code);
        if (error) {
          throw error;
        }
        acceptRecoverySession(data.session);
      } else {
        const { data, error } = await client.auth.getSession();
        if (error) {
          throw error;
        }
        acceptRecoverySession(data.session);
      }
    } catch {
      clearSensitiveUrl();
      showState("invalid");
      return;
    }

    if (!recoverySessionReady) {
      showState("invalid");
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    formMessage.className = "message hidden";

    if (password.value.length < 8) {
      showFormError("รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร");
      return;
    }
    if (password.value !== confirmation.value) {
      showFormError("รหัสผ่านและการยืนยันไม่ตรงกัน");
      return;
    }

    submitButton.disabled = true;
    submitButton.textContent = "กำลังเปลี่ยนรหัสผ่าน…";
    try {
      const { error } = await client.auth.updateUser({
        password: password.value,
      });
      if (error) {
        throw error;
      }
      password.value = "";
      confirmation.value = "";
      await client.auth.signOut();
      showState("success");
    } catch {
      showFormError("เปลี่ยนรหัสผ่านไม่สำเร็จ กรุณาขอลิงก์ใหม่แล้วลองอีกครั้ง");
      submitButton.disabled = false;
      submitButton.textContent = "เปลี่ยนรหัสผ่าน";
    }
  });

  initialize();
})();
