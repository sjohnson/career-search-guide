document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".source-task-list[data-reorder-url]").forEach((list) => {
    if (typeof Sortable === "undefined") return;
    const url = list.dataset.reorderUrl;
    Sortable.create(list, {
      handle: ".drag-handle",
      animation: 150,
      onEnd: async () => {
        const order = [...list.querySelectorAll("[data-task-id]")].map((el) => el.dataset.taskId);
        await fetch(url, {
          method: "POST",
          headers: csrfHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ order }),
        });
      },
    });
  });

  document.body.addEventListener("click", (event) => {
    if (!event.target.closest(".date-picker-popover") && !event.target.closest(".date-picker-trigger")) {
      document.querySelectorAll(".date-picker-popover").forEach((el) => {
        el.innerHTML = "";
      });
    }
  });
});
