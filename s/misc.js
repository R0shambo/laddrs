function toggle_visibility(id) {
  var e = document.getElementById(id);
  if(e.style.display == 'block')
    e.style.display = 'none';
  else
    e.style.display = 'block';
}

function clearButterBar() {
  document.getElementById("butter").style.display = 'none';
}

function toggleChatBox(force) {
  var box = document.getElementById("chatbox");
  var sendbox = document.getElementById("sendchatbox");
  var container = document.getElementById("chat-container");
  if (force || box.style.display == "none") {
    box.style.display = 'block';
    box.style.width = '392px';
    box.scrollTop = box.scrollHeight;
    sendbox.style.display = 'block';
    container.style.opacity = 1;
  }
  else {
    box.style.display = 'none';
    sendbox.style.display = 'none';
    document.getElementById("presence-container").style.display = 'none';
    container.style.opacity = 0.75;
  }
}

function togglePresence(force) {
  var box = document.getElementById("chatbox");
  var presence = document.getElementById("presence-container");
  if (force || presence.style.display != "block") {
    presence.style.display = 'block';
  }
  else {
    presence.style.display = 'none';
  }
}

function toggleTimestamps() {
  var cb = document.getElementById("chatbox")
  var scrolldown = true;
  if (cb.scrollTop < cb.scrollHeight - cb.offsetHeight) {
    scrolldown = false;
  }
  var style = document.getElementById("timestamp-style");
  style.disabled = !style.disabled;
  if (scrolldown) {
    cb.scrollTop = cb.scrollHeight;
  }
}
