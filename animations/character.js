// animations/character.js
// Controls characters: main (center / point left / point right / point left-up),
// plus an optional extra character ("confused") that is swapped in per scene.
// Only the character named in the scene is visible.
const Character = {
  els: { main: null, confused: null },

  init(mainEl, confusedEl) {
    this.els.main = mainEl;
    this.els.confused = confusedEl;
    this.show("main");
  },

  // Show one character (hide the rest). name in ["main", "confused"].
  show(name) {
    name = name || "main";
    for (const key in this.els) {
      const el = this.els[key];
      if (el) el.classList.toggle("char--active", key === name);
    }
  },

  center() {
    this.show("main");
    this.els.main.classList.remove("char--left", "char--right");
  },

  pointLeft() {
    this.show("main");
    this.els.main.classList.remove("char--right");
    this.els.main.classList.add("char--left");
  },

  // Character flips to face the left (no body rotation) - used for the
  // opening line pointing at object A on the top-left.
  pointLeftUp() {
    this.show("main");
    this.els.main.classList.remove("char--right");
    this.els.main.classList.add("char--left");
  },

  pointRight() {
    this.show("main");
    this.els.main.classList.remove("char--left");
    this.els.main.classList.add("char--right");
  },
};