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
  if (force) {
    box.style.display = force;
    box.scrollTop = box.scrollHeight;
    sendbox.style.display = force;
  }
  else if (box.style.display == "none") {
    box.style.display = 'block';
    box.scrollTop = box.scrollHeight;
    sendbox.style.display = 'block';
  }
  else {
    box.style.display = 'none';
    sendbox.style.display = 'none';
  }
}
