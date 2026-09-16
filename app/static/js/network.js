// Keep the "N more due" disclosure open across out-of-band swaps.
//
// Every network action repaints all three sections, which rebuilds the
// <details> element and resets it to closed. Working through a backlog means
// acting on several people in a row, so losing the expansion after each click
// defeats the point of having the overflow list.
(function () {
  var isOpen = false;

  // The toggle event does not bubble, so listen in the capture phase.
  document.addEventListener(
    "toggle",
    function (event) {
      if (event.target.classList.contains("reach-out-overflow")) {
        isOpen = event.target.open;
      }
    },
    true
  );

  document.addEventListener("htmx:afterSettle", function () {
    if (!isOpen) return;
    var details = document.querySelector(".reach-out-overflow");
    if (details) details.open = true;
  });
})();
