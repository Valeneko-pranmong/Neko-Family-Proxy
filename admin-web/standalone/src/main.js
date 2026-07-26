import * as api from "./api.js";
import { createSessionController } from "./session.js";
import { createStore } from "./state.js";
import { couponForm, renderSection } from "./sections/render.js";
import { loginView, shellView } from "./ui/layout.js";
import { toast } from "./ui/toast.js";

const root = document.querySelector("#app");
const store = createStore();
let loginError = "";

function render() {
  if (!session.authenticated) {
    root.innerHTML = loginView(loginError);
    return;
  }
  root.innerHTML = shellView(store.state.active, session.viewer);
  const content = root.querySelector("#content");
  if (store.state.loading) {
    content.innerHTML = `<div class="panel"><div class="empty">กำลังโหลดข้อมูล…</div></div>`;
  } else if (store.state.error) {
    content.innerHTML = `<div class="panel"><div class="form-error">${store.state.error}</div></div>`;
  } else {
    content.innerHTML = renderSection(store.state.active, store.state.data[store.state.active]);
    if (store.state.couponFormOpen) {
      const host = root.querySelector("#coupon-form-host");
      if (host) host.innerHTML = couponForm();
    }
  }
}

async function load(section = store.state.active) {
  store.patch({ loading: true, error: "" });
  try {
    const result = await api.loadResource(section);
    store.patch({
      data: { ...store.state.data, [section]: result.data },
      loading: false,
    });
  } catch (error) {
    if (error?.status === 401) {
      await session.logout().catch(() => {});
      return;
    }
    store.patch({
      loading: false,
      error: error instanceof Error ? error.message : "โหลดข้อมูลไม่สำเร็จ",
    });
  }
}

async function action(name, id) {
  const row = (store.state.data[store.state.active] || []).find((item) => item.id === id);
  if (name === "toggle_user_status") {
    const nextStatus = row?.status === "active" ? "suspended" : "active";
    if (!window.confirm(`ยืนยันเปลี่ยนสถานะสมาชิกเป็น ${nextStatus} หรือไม่`)) return;
    await run({ action: "set_user_status", userId: id, status: nextStatus });
    return;
  }
  if (name === "extend_license") {
    const days = Number(window.prompt("ต้องการต่ออายุกี่วัน", "30"));
    if (!Number.isInteger(days) || days < 1) return;
    await run({ action: "extend_license", licenseId: id, days });
    return;
  }
  const labels = {
    revoke_license: "ยกเลิก License นี้หรือไม่",
    revoke_session: "ยกเลิก session นี้หรือไม่",
    revoke_batch: "ยกเลิกคูปองทั้งชุดนี้หรือไม่",
  };
  if (!window.confirm(labels[name] || "ยืนยันคำสั่งนี้หรือไม่")) return;
  const payload = {
    revoke_license: { action: name, licenseId: id },
    revoke_session: { action: name, sessionId: id },
    revoke_batch: { action: name, batchId: id },
  }[name];
  if (payload) await run(payload);
}

async function run(payload) {
  try {
    await api.runAction(payload);
    toast("ดำเนินการสำเร็จ", "success");
    await load();
  } catch (error) {
    toast(error instanceof Error ? error.message : "ดำเนินการไม่สำเร็จ", "error");
  }
}

async function submitCoupon(form) {
  const formData = new FormData(form);
  try {
    const result = await api.runAction({
      action: "generate_coupons",
      productCode: formData.get("productCode"),
      durationDays: Number(formData.get("durationDays")),
      quantity: Number(formData.get("quantity")),
      note: formData.get("note") || null,
    });
    store.patch({ couponFormOpen: false });
    toast(`สร้างคูปอง ${result.codes?.length || 0} รายการแล้ว`, "success");
    if (result.codes?.length) {
      window.prompt("คัดลอกคูปองชุดนี้ เก็บไว้ครั้งเดียว", result.codes.join("\n"));
    }
    await load("coupons");
  } catch (error) {
    toast(error instanceof Error ? error.message : "สร้างคูปองไม่สำเร็จ", "error");
  }
}

const session = createSessionController(() => {
  loginError = "";
  render();
});

store.subscribe(render);

root.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (event.target.id === "login-form") {
    const form = new FormData(event.target);
    const email = form.get("email");
    const password = form.get("password");
    try {
      await session.login(String(email || ""), String(password || ""));
      await load("overview");
    } catch (error) {
      loginError = error instanceof Error ? error.message : "เข้าสู่ระบบไม่สำเร็จ";
      render();
    }
  } else if (event.target.id === "coupon-form") {
    await submitCoupon(event.target);
  }
});

root.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-section], [data-action]");
  if (!target) return;
  if (target.dataset.section) {
    store.patch({ active: target.dataset.section, couponFormOpen: false });
    await load(target.dataset.section);
    return;
  }
  const name = target.dataset.action;
  if (name === "logout") {
    await session.logout().catch(() => {});
    return;
  }
  if (name === "show-coupon-form") {
    store.patch({ couponFormOpen: true });
    return;
  }
  if (name === "hide-coupon-form") {
    store.patch({ couponFormOpen: false });
    return;
  }
  await action(name, target.dataset.id);
});

render();
void session.restore().then((restored) => {
  if (restored) void load("overview");
});
