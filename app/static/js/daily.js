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
        headers: csrfHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ order }),
      });
    },
  });
});

function confirmRemoveTask(form) {
  const alsoDelete = form.querySelector('[name="delete_source"]')?.checked;
  if (alsoDelete) {
    return confirm(
      "Remove from today's plan and permanently delete this task from your source list?"
    );
  }
  return confirm("Remove this task from today's plan only? It will stay in your source task list.");
}
