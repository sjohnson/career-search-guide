document.addEventListener("DOMContentLoaded", () => {
  const list = document.getElementById("active-task-list");
  if (!list || typeof Sortable === "undefined") return;

  const planDate = list.dataset.planDate;

  Sortable.create(list, {
    handle: ".drag-handle",
    animation: 150,
    onEnd: async () => {
      const order = [...list.querySelectorAll("[data-task-id]")].map(
        (el) => el.dataset.taskId
      );
      await fetch(`/daily/${planDate}/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order }),
      });
    },
  });
});
