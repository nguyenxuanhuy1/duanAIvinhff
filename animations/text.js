// animations/text.js
// Controls the caption text: set + fade-in reveal.
const TextCtl = {
  el: null,

  init(el) {
    this.el = el;
  },

  setText(str) {
    this.el.textContent = str || "";
    this.el.classList.remove("text--in");
    // Force reflow so the fade-in transition restarts on every scene.
    void this.el.offsetWidth;
    this.el.classList.add("text--in");
  },
};