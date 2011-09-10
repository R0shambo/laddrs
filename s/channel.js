laddrs = {};

laddrs.ladder_name = '';
laddrs.user_id = '';
laddrs.token = '';
laddrs.throbber = '';
laddrs.last_chat_msg = 0;
laddrs.first_open = true;
laddrs.colors = {};
laddrs.colors_picked = 0;
laddrs.color_options = [
  '#006', '#606', '#900', '#633', '#030', '#036',
  '#00c', '#90c', '#c30', '#330', '#066',
  '#00f', '#c39', '#933', '#663', '#099',
];

laddrs.pickColor = function() {
  return laddrs.color_options[laddrs.colors_picked++ % laddrs.color_options.length]
};

laddrs.XHR = function() {
  if (window.XMLHttpRequest) {
    return new XMLHttpRequest();
  } else if (window.ActiveXObject) {
    return new ActiveXObject("Microsoft.XMLHTTP");
  }
}

laddrs.Action = function(xhr, action, params) {
  if (!params) {
    params = {};
  }
  params.user_id = laddrs.user_id;
  if (!xhr) {
    xhr = laddrs.XHR();
  }
  var url = "/channel/" + laddrs.ladder_name + "/" + action;
  laddrs.POST(xhr, url, params)
}

laddrs.POST = function(xhr, url, map) {
  var params = new Array();
  for (var i in map) {
    params.push(encodeURIComponent(i) + "=" + encodeURIComponent(map[i]));
  }
  xhr.open("POST", url, true);
  xhr.setRequestHeader("Content-type", "application/x-www-form-urlencoded");
  xhr.send(params.join("&"));
}

laddrs.StartChannel = function(ladder_name, user_id) {
  laddrs.ladder_name = ladder_name;
  laddrs.user_id = user_id;
  laddrs.GetTokenAndOpenChannel();
}

laddrs.GetTokenAndOpenChannel = function() {
  var xhr = laddrs.XHR();
  xhr.onreadystatechange=function() {
    if (xhr.readyState==4 && xhr.status==200) {
      laddrs.token = xhr.responseText;
      laddrs.OpenChannel();
    }
  }
  laddrs.Action(xhr, "get-token");
}

laddrs.OpenChannel = function() {
  var channel = new goog.appengine.Channel(laddrs.token);
  var handler = {
    'onopen': laddrs.ChannelOpened,
    'onmessage': laddrs.ChannelMessaged,
    'onerror': laddrs.ChannelErrored,
    'onclose': laddrs.ChannelClosed,
  };
  var socket = channel.open(handler);
}

laddrs.SendChatMsg = function(el) {
  var input = document.getElementById("sendchatmsg");
  var msg = input.value;
  if (msg) {
    params = {
      m: msg,
    }
    // Send the chat message over XHR
    laddrs.Action(null, "send-chat", params);
    input.value = "";
    /*var t = new Date();
    var c = {
      t: t.getTime(),
      n: "Player",
      m: msg,
    };
    var chat = new Array(c);
    laddrs.AddChatMessages(chat);
    */
  }
}

laddrs.AddChatMessages = function(chat) {
  var cb = document.getElementById("chatbox")
  var scrolldown = true;
  if (cb.scrollTop < cb.scrollHeight - cb.offsetHeight) {
    scrolldown = false;
  }
  for (var i in chat) {
    var c = chat[i];
    var div = document.createElement("div");
    var t = new Date(c.t * 1000);
    if (!laddrs.colors[c.n]) {
      laddrs.colors[c.n] = laddrs.pickColor();
    }
    div.title = t.toLocaleDateString() + " " + t.toLocaleTimeString();

    if (c['s']) {
      div.className = "system";
      div.innerText = c.n + " " + c.s
    }
    else {
      div.className = "message";
      var name = document.createElement("span")
      name.className = "name";
      name.style.color = laddrs.colors[c.n];
      name.innerText = c.n + ": ";
      var text = document.createElement("span")
      text.className = "chatmsg";
      text.innerHTML = c.m;
      div.appendChild(name);
      div.appendChild(text);
    }
    cb.appendChild(div);
    laddrs.last_chat_msg = c.t;
    if (!laddrs.throbber) {
      laddrs.ThrobChatHeader();
    }
    if (scrolldown) {
      cb.scrollTop = cb.scrollHeight;
    }
  }
}

laddrs.ThrobChatHeader = function() {
  var ch = document.getElementById("chat-header");
  var bg = ch.className;
  if (ch.className == "") {
    ch.className = "throb";
  }
  else {
    ch.className = "";
  }
  laddrs.throbber = setTimeout("laddrs.ThrobChatHeader();", 1000);
}
laddrs.StopThrobbing = function() {
  clearTimeout(laddrs.throbber);
  document.getElementById("chat-header").className="";
}

laddrs.ChannelOpened = function() {
  if (laddrs.first_open) {
    document.getElementById("chat-container").style.display = 'block';
    toggleChatBox('block');
    laddrs.first_open = false;
  }
  var newdiv = document.createElement("div");
  var now = new Date();
  newdiv.className = "system";
  newdiv.appendChild(document.createTextNode("Chat connected."));
  newdiv.title = now.toLocaleDateString() + " " + now.toLocaleTimeString();
  document.getElementById("chatbox").appendChild(newdiv);

  // fetch chat history
  params = {
    last_chat_msg: laddrs.last_chat_msg,
  };
  var xhr = laddrs.XHR();
  xhr.onreadystatechange=function() {
    if (xhr.readyState==4 && xhr.status==200) {
      chat = JSON.parse(xhr.responseText);
      laddrs.AddChatMessages(chat);
    }
  }
  laddrs.Action(xhr, "get-chat-history", params);
}
laddrs.ChannelErrored = function(e) {
  var newdiv = document.createElement("div");
  var now = new Date();
  newdiv.className = "system";
  newdiv.appendChild(document.createTextNode("Error occured: " + e.code + " " + e.description));
  newdiv.title = now.toLocaleDateString() + " " + now.toLocaleTimeString();
  cb = document.getElementById("chatbox")
  cb.appendChild(newdiv);
  cb.scrollTop = cb.scrollHeight;
}
laddrs.ChannelMessaged = function(m) {
  var msg = JSON.parse(m.data);
  if (msg.chat) {
    laddrs.AddChatMessages(msg.chat);
    laddrs.ThrobChatHeader();
  }
}
laddrs.ChannelClosed = function() {
  var newdiv = document.createElement("div");
  var now = new Date();
  newdiv.className = "system";
  newdiv.appendChild(document.createTextNode("Chat disconnected."));
  newdiv.title = now.toLocaleDateString() + " " + now.toLocaleTimeString();
  cb = document.getElementById("chatbox")
  cb.appendChild(newdiv);
  cb.scrollTop = cb.scrollHeight;
  laddrs.GetTokenAndOpenChannel();
}

/*


  var token = '{{ token }}';
  var channel = new goog.appengine.Channel(token);
  var handler = {
    'onopen': onOpened,
    'onmessage': onMessage,
    'onerror': function() {},
    'onclose': function() {}
  };
  var socket = channel.open(handler);
  socket.onopen = onOpened;
  socket.onmessage = onMessage;
}

*/
