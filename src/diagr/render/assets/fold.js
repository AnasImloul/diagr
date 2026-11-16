// The state after each frame of a scenario, from its frames alone: what every part of the diagram shows at each
// frame, so stepping back or scrubbing shows exactly what playing would. Node loads it too, for the tests.
function diagrStates(frames) {
  var states = [{}];
  for (var i = 1; i < frames.length; i++) {
    var s = Object.assign({}, states[i - 1]), set = frames[i].set;
    for (var key in set) { if (set[key] === null) delete s[key]; else s[key] = set[key]; }
    states.push(s);
  }
  return states;
}
if (typeof module !== "undefined") module.exports = diagrStates;
