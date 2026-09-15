// templates/animation.js
// Fixed animation library. The Designer AI may only reference these names
// in Scene JSON ("animation": "<name>") - it never writes new animation code.
const AnimationLibrary = {
  intro(ctx)   { Character.center(); ImagesCtl.hideAll(); ctx.stage.classList.remove("fade-out"); },
  outro(ctx)   { Character.center(); ctx.stage.classList.remove("fade-out"); }, // no dark fade at the end
  fadeIn(ctx)  { ctx.stage.classList.remove("fade-out"); ctx.stage.classList.add("fade-in"); },
  fadeOut(ctx) { ctx.stage.classList.remove("fade-in"); ctx.stage.classList.add("fade-out"); },
  slideLeft(ctx)  { ctx.stage.classList.add("slide-left"); },
  slideRight(ctx) { ctx.stage.classList.add("slide-right"); },
  zoomIn(ctx)  { ctx.stage.classList.add("zoom-in"); },
  zoomOut(ctx) { ctx.stage.classList.add("zoom-out"); },
  showA(ctx)   { ImagesCtl.showA(); },
  showB(ctx)   { ImagesCtl.showB(); },
  compare(ctx) { ImagesCtl.showBoth(); },
  showConfused(ctx) { Character.show("confused"); },
};

function getActiveCharacter(name) {
  // "pointLeftUp", "pointLeft", "pointRight", "center" → main character with a pose
  // "confused" → dedicated extra character
  if (name === "confused") return name;
  return "main";
}

// Grab the stage elements once and wire up the controllers. The <script> tags
// live at the end of <body>, so every element already exists here.
function initStage() {
  const stage = document.getElementById("stage");
  const charEl = document.getElementById("character");
  const confusedEl = document.getElementById("character-confused");
  const imgA = document.getElementById("image-a");
  const imgB = document.getElementById("image-b");
  const textEl = document.getElementById("caption");

  Character.init(charEl, confusedEl);
  ImagesCtl.init(imgA, imgB);
  TextCtl.init(textEl);

  return { stage };
}

// Puts the stage into one scene's visual state. Pure state-setting, no waiting:
// the playback loop below and recorder.py's capture mode both drive the timing.
function applyScene(scene, ctx) {
  // Named animation trigger (visual effect on the stage)
  const anim = AnimationLibrary[scene.animation];
  if (anim) {
    anim(ctx);
  } else if (scene.animation) {
    console.warn("Unknown animation name:", scene.animation);
  }

  // Which image(s) to show this scene
  if (scene.image === "A") ImagesCtl.showA();
  else if (scene.image === "B") ImagesCtl.showB();
  else if (scene.image === "both") ImagesCtl.showBoth();
  else ImagesCtl.hideAll();

  // Character pose this scene (main character + pose, or extra character)
  Character.show(getActiveCharacter(scene.character));
  if (scene.character === "pointLeft") Character.pointLeft();
  else if (scene.character === "pointLeftUp") Character.pointLeftUp();
  else if (scene.character === "pointRight") Character.pointRight();
  else if (scene.character === "center") Character.center();

  // Caption text this scene
  TextCtl.setText(scene.text);
}

async function playScene(sceneData, ctx) {
  for (const scene of sceneData.scenes) {
    applyScene(scene, ctx);
    const durationMs = (scene.duration || 4) * 1000;
    await new Promise((resolve) => setTimeout(resolve, durationMs));
  }

  // Signals recorder.py that playback has finished and it's safe to stop recording.
  window.__SCENE_DONE__ = true;
}

// SCENE_DATA is injected as a literal by renderer.py before this script runs.
const STAGE_CTX = initStage();

// Capture mode (recorder.capture_scenes): recorder.py steps through the scenes
// itself and screenshots each settled frame, so the page must NOT auto-play —
// otherwise playback would race the screenshots. The flag is set by an init
// script that runs before this file.
window.__applyScene = function (index) {
  applyScene(SCENE_DATA.scenes[index], STAGE_CTX);
};

if (!window.__CAPTURE_MODE__) {
  playScene(SCENE_DATA, STAGE_CTX);
}
