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
laddrs.pinger = null;
laddrs.connection_attempt = 1;
laddrs.reconnect_delay = 5000;
laddrs.reconnecting = false;
laddrs.socket = {
  readyState: 3,
};
laddrs.sendchatenabled = false;

laddrs.pickColor = function() {
  return laddrs.color_options[laddrs.colors_picked++ % laddrs.color_options.length]
};

laddrs.XHR = function() {
  return new XMLHttpRequest();
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
  if (laddrs.pinger) {
    clearTimeout(laddrs.pinger);
  }
  var xhr = laddrs.XHR();
  xhr.onreadystatechange=function() {
    if (xhr.readyState==4) {
      laddrs.reconnecting = false;
      if (xhr.status==200) {
        laddrs.token = xhr.responseText;
        laddrs.OpenChannel();
      }
      else {
        var e = {
          code: xhr.status,
          description: "Chat connection failed",
        }
        laddrs.ChannelErrored(e);
        laddrs.ChannelClosed();
      }
    }
  }
  if (!laddrs.first_open) {
    var newdiv = document.createElement("div");
    var now = new Date();
    newdiv.className = "system";
    newdiv.appendChild(document.createTextNode("Reconnecting..."));
    newdiv.title = now.toLocaleDateString() + " " + now.toLocaleTimeString();
    cb = document.getElementById("chatbox")
    cb.appendChild(newdiv);
    cb.scrollTop = cb.scrollHeight;
  }
  laddrs.Action(xhr, "get-token");
}

laddrs.OpenChannel = function() {
  if (laddrs.socket.readyState > 1) {
    var channel = new goog.appengine.Channel(laddrs.token);
    var handler = {
      'onopen': laddrs.ChannelOpened,
      'onmessage': laddrs.ChannelMessaged,
      'onerror': laddrs.ChannelErrored,
      'onclose': laddrs.ChannelClosed,
    };
    var timeout = 30000 * laddrs.connection_attempt++;
    timeout = timeout > 180000 ? 180000 : timeout;
    clearTimeout(laddrs.pinger);
    laddrs.pinger = setTimeout("laddrs.PingChannel();", timeout);
    laddrs.socket = channel.open(handler);
  }
}

laddrs.SendChatMsg = function(el) {
  var input = document.getElementById("sendchatmsg");
  var msg = input.value;
  if (msg) {
    params = {
      m: msg,
    }
    // Send the chat message over XHR
    var xhr = laddrs.XHR();
    xhr.onreadystatechange=function() {
      if (xhr.readyState==4 && xhr.status!=200) {
        var e = {
          code: xhr.status,
          description: "Error sending chat message",
        };
        laddrs.ChannelErrored(e);
      }
    }
    laddrs.Action(null, "send-chat", params);
    input.value = "";
  }
}

laddrs.GetLadderUpdate = function() {
  var xhr = laddrs.XHR();
  xhr.onreadystatechange=function() {
    if (xhr.readyState==4 && xhr.status==200) {
      var msg = {};
      msg.data = xhr.responseText
      laddrs.ChannelMessaged(msg)
    }
  }
  laddrs.Action(xhr, "get-ladder-data", null);
}

laddrs.GetTime = function(t) {
  return (t.getHours() < 10 ? "0" + t.getHours() : t.getHours()) + ":" + (t.getMinutes() < 10 ? "0" + t.getMinutes() : t.getMinutes());
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
      div.innerHTML = c.n + " " + c.s
    }
    else {
      div.className = "message";
      var ts = document.createElement("span");
      ts.className = "ts";
      ts.innerHTML = laddrs.GetTime(t) + " ";
      var name = document.createElement("span");
      name.className = "name";
      name.style.color = laddrs.colors[c.n];
      name.innerHTML = c.n + ": ";
      var text = document.createElement("span");
      text.className = "chatmsg";
      text.innerHTML = c.m;
      div.appendChild(ts);
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

laddrs.SetPresence = function(presence) {
  var div = document.getElementById("chat-presence");
  div.innerHTML = "";
  for (var i in presence) {
    var name = presence[i];
    var player = document.createElement("div")
    if (!laddrs.colors[name]) {
      laddrs.colors[name] = laddrs.pickColor();
    }
    player.style.color = laddrs.colors[name];
    player.innerHTML = name;
    div.appendChild(player);
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

laddrs.EnableSendChatBox = function(bool) {
  if (laddrs.sendchatboxenabled != bool) {
    laddrs.sendchatboxenabled = bool;
    var sendchatbox = document.getElementById("sendchatbox");
    sendchatbox.disabled = !bool;
    sendinputs = sendchatbox.getElementsByTagName("input");
    for (var i in sendinputs) {
      var input = sendinputs[i];
      input.disabled = !bool;
    }
  }
}

laddrs.ChannelOpened = function() {
  laddrs.reconnecting = false;
  clearTimeout(laddrs.pinger);
  laddrs.pinger = setTimeout("laddrs.PingChannel();", 120000);
  laddrs.EnableSendChatBox(true);
  if (laddrs.first_open) {
    document.getElementById("chat-container").style.display = 'block';
    toggleChatBox(true);
    laddrs.first_open = false;
  }
  else {
    var newdiv = document.createElement("div");
    var now = new Date();
    newdiv.className = "system";
    newdiv.appendChild(document.createTextNode("Chat reconnected."));
    newdiv.title = now.toLocaleDateString() + " " + now.toLocaleTimeString();
    var cb = document.getElementById("chatbox")
    cb.appendChild(newdiv);
    cb.scrollTop = cb.scrollHeight;
  }

  laddrs.connection_attempt = 1;
  laddrs.reconnect_delay = 5000;

  // fetch chat history
  var params = {
    last_chat_msg: laddrs.last_chat_msg,
  };
  var xhr = laddrs.XHR();
  xhr.onreadystatechange=function() {
    if (xhr.readyState==4 && xhr.status==200) {
      var msg = {};
      msg.data = xhr.responseText
      laddrs.ChannelMessaged(msg)
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
  if (laddrs.socket.readyState == 1) {
    clearTimeout(laddrs.pinger);
    laddrs.alive = true;
    laddrs.PingChannel(20000, true);
  }
  else {
    laddrs.ChannelClosed();
  }
}

laddrs.ChannelMessaged = function(m) {
  var msg = JSON.parse(m.data);
  laddrs.alive = true;
  if (msg.chat) {
    laddrs.AddChatMessages(msg.chat);
    laddrs.ThrobChatHeader();
  }
  if (msg.presence) {
    laddrs.SetPresence(msg.presence);
  }
  if (msg.ladder_updated) {
    laddrs.GetLadderUpdate();
  }
  if (msg.players) {
    var d = document.getElementById("players");
    d.innerHTML = msg.players;
  }
  if (msg.match_history) {
    var d = document.getElementById("match_history");
    d.innerHTML = msg.match_history;
  }
}

laddrs.ChannelClosed = function() {
  if (!laddrs.reconnecting) {
    laddrs.reconnecting = true;
    laddrs.EnableSendChatBox(false);
    if (!laddrs.first_open) {
      var newdiv = document.createElement("div");
      var now = new Date();
      newdiv.className = "system";
      newdiv.appendChild(document.createTextNode("Chat disconnected. Will retry in " + laddrs.reconnect_delay / 1000 + " seconds."));
      newdiv.title = now.toLocaleDateString() + " " + now.toLocaleTimeString();
      cb = document.getElementById("chatbox")
      cb.appendChild(newdiv);
      cb.scrollTop = cb.scrollHeight;
    }
    setTimeout('laddrs.GetTokenAndOpenChannel();', laddrs.reconnect_delay);
    laddrs.reconnect_delay *= 2;
    if (laddrs.reconnect_delay > 120000) {
      laddrs.reconnect_delay = 120000;
    }
  }
}

laddrs.PingChannel = function(wait, disablesendchatbox) {
  var use_wait = wait ? wait : 120000;
  if (laddrs.alive) {
    if (disablesendchatbox) {
      laddrs.EnableSendChatBox(false);
    }
    laddrs.alive = false;
    laddrs.Action(null, "ping", null);
    clearTimeout(laddrs.pinger);
    laddrs.pinger = setTimeout("laddrs.PingChannel();", use_wait);
  }
  else {
    if (laddrs.socket.readyState < 2) {
      if (!laddrs.first_open) {
        var newdiv = document.createElement("div");
        var now = new Date();
        newdiv.className = "system";
        newdiv.appendChild(document.createTextNode("Chat stalled."));
        newdiv.title = now.toLocaleDateString() + " " + now.toLocaleTimeString();
        cb = document.getElementById("chatbox")
        cb.appendChild(newdiv);
        cb.scrollTop = cb.scrollHeight;
      }
      laddrs.socket.close();
    }
  }
}
