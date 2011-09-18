laddrs = {};

// Logging is good. So let's see if we can actually log stuff.
if (window.console) {
  console.log("Yay! console.log() exists!");
}
else {
  // This is needed or IE will fail. I fucking hate IE.
  window.console = {};
  window.console.debug = function() {};
  window.console.log = function() {};
  window.console.warn = function() {};
  window.console.error = function() {};
}

laddrs.ladder_name = '';
laddrs.user_id = '';
laddrs.version = 0;
laddrs.token = '';
laddrs.token_refresh = false;
laddrs.token_refreshed = false;
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
laddrs.reconnect = false;
laddrs.reconnect_delay = 5000;
laddrs.socket = {
  readyState: 3,
};
laddrs.sendchatenabled = false;
laddrs.pingwait = 30000;
laddrs.toastSound = false;
laddrs.pingtime = 0;

// Successful Ladder Chat requires Twelve Steps. Here they are:

// Step 1 - Start channel for the first time.
laddrs.StartChannel = function(ladder_name, user_id, version) {
  laddrs.ladder_name = ladder_name;
  laddrs.user_id = user_id;
  laddrs.version = version;
  laddrs.GetTokenAndOpenChannel();
}

// Step 2 - Get token for opening the channel.
laddrs.GetTokenAndOpenChannel = function() {
  console.debug("GetTokenAndOpenChannel called.");
  if (laddrs.pinger) {
    clearTimeout(laddrs.pinger);
  }
  var xhr = laddrs.XHR();
  xhr.onreadystatechange=function() {
    if (xhr.readyState==4) {
      if (xhr.status==200) {
        if (xhr.responseText == 'RELOAD') {
          window.location.reload(true);
        }
        else {
          laddrs.token = xhr.responseText;
          laddrs.OpenChannel();
        }
      }
      else {
        var e = {
          code: xhr.status,
          description: "Chat connection failed",
        }
        laddrs.ChannelErrored(e);
      }
    }
  }
  if (laddrs.token) {
    var newdiv = document.createElement("div");
    var now = new Date();
    newdiv.className = "system";
    newdiv.appendChild(document.createTextNode("Reconnecting..."));
    newdiv.title = now.toLocaleDateString() + " " + now.toLocaleTimeString();
    cb = document.getElementById("chatbox")
    cb.appendChild(newdiv);
    cb.scrollTop = cb.scrollHeight;
  }
  laddrs.pinger = setTimeout("laddrs.PingChannel();", 30000);
  laddrs.Action(xhr, "get-token", { version: laddrs.version });
  laddrs.token_refreshed = laddrs.token_refresh;
  laddrs.token_refresh = false;
}

// Step 3 - Open channel using shiny new token.
laddrs.OpenChannel = function() {
  console.debug("OpenChannel called.");
  if (laddrs.socket.readyState == 3) {
    var channel = new goog.appengine.Channel(laddrs.token);
    var handler = {
      'onopen': laddrs.ChannelOpened,
      'onmessage': laddrs.ChannelMessaged,
      'onerror': laddrs.ChannelErrored,
      'onclose': laddrs.ChannelClosed,
    };
    clearTimeout(laddrs.pinger);
    laddrs.pinger = setTimeout("laddrs.PingChannel(30000);", 30000);
    laddrs.socket = channel.open(handler);
  }
  else {
    console.log("OpenChannel called, but socket %o is already active", laddrs.socket);
    clearTimeout(laddrs.pinger);
    laddrs.pinger = setTimeout("laddrs.PingChannel(30000);", 30000);
  }
}

// Step 4 - The channel is opened! Rejoice and give thanks!
laddrs.ChannelOpened = function() {
  console.debug("Channel Opened!");
  clearTimeout(laddrs.pinger);
  clearTimeout(laddrs.reconnect);
  laddrs.pinger = setTimeout("laddrs.PingChannel(30000);", 30000);
  laddrs.EnableSendChatBox(true);
  if (laddrs.first_open) {
    document.getElementById("chat-container").style.display = 'block';
    toggleChatBox(true);
    laddrs.first_open = false;
  }
  else if (!laddrs.token_refreshed) {
    var newdiv = document.createElement("div");
    var now = new Date();
    newdiv.className = "system";
    newdiv.appendChild(document.createTextNode("Chat reconnected."));
    newdiv.title = now.toLocaleDateString() + " " + now.toLocaleTimeString();
    var cb = document.getElementById("chatbox")
    cb.appendChild(newdiv);
    cb.scrollTop = cb.scrollHeight;
  }
  laddrs.token_refreshed = false;
  laddrs.reconnect_delay = 5000;
}

// Step 5 - Handle all the fun messages received on the channel.
laddrs.ChannelMessaged = function(m) {
  var msg = JSON.parse(m.data);
  laddrs.alive = true;
  if (msg.ping) {
    laddrs.pingtime = msg.ping;
  }
  if (msg.chat) {
    if (laddrs.AddChatMessages(msg.chat) &&
        (!window.isActive || document.getElementById("chatbox").style.display == 'none')) {
      laddrs.ThrobChatHeader();
      if (laddrs.toastSound) {
        console.debug("chirp!");
        laddrs.toastSound.play();
      }
    }
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
  if (msg.get_chat_history) {
    // fetch chat history
    var params = {
      last_chat_msg: laddrs.last_chat_msg,
    };
    var xhr = laddrs.XHR();
    xhr.onreadystatechange=function() {
      if (xhr.readyState==4) {
        if (xhr.status==200) {
          var msg = {};
          msg.data = xhr.responseText
          laddrs.ChannelMessaged(msg)
          console.log("History updated.");
        }
        else {
          var e = {
            code: xhr.status,
            description: "Error getting chat history",
          };
          laddrs.ChannelErrored(e);
        }
      }
    }
    console.log("Fetching chat history...");
    laddrs.Action(xhr, "get-chat-history", params);
    if (laddrs.last_chat_msg > 0) {
      laddrs.GetLadderUpdate();
    }
  }
  if (msg.ping_back) {
    laddrs.pingtime = msg.ping_back;
    console.log("Server requested a ping");
    laddrs.PingChannel(30000);
  }
}

// Step 6 - Append those messages to the chatbox.
laddrs.AddChatMessages = function(chat) {
  var addedMessage = false;
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
      laddrs.colors[c.n] = laddrs.PickColor();
    }
    div.title = t.toLocaleDateString() + " " + t.toLocaleTimeString();

    if (c['s']) {
      div.className = "system";
      div.innerHTML = c.n + " " + c.s
    }
    else if (c['m']) {
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
    else {
      continue;
    }
    addedMessage = true;
    cb.appendChild(div);
    laddrs.last_chat_msg = c.t;
    if (scrolldown) {
      cb.scrollTop = cb.scrollHeight;
    }
  }
  return addedMessage;
}

// Step 7 - Update presence information when people join or leave.
laddrs.SetPresence = function(presence) {
  var div = document.getElementById("chat-presence");
  div.innerHTML = "";
  for (var i in presence) {
    var name = presence[i];
    var player = document.createElement("div")
    if (!laddrs.colors[name]) {
      laddrs.colors[name] = laddrs.PickColor();
    }
    player.style.color = laddrs.colors[name];
    player.innerHTML = name;
    div.appendChild(player);
  }
}

// Step 8 - Update ladder info when someone uploads a new match.
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

// Step 9 - Repeatedly ping the channel to make sure we're still alive.
laddrs.PingChannel = function(wait, disablesendchatbox) {
  clearTimeout(laddrs.pinger);
  laddrs.pingwait = wait || laddrs.pingwait;
  if (laddrs.alive) {
    if (!disablesendchatbox) {
      laddrs.EnableSendChatBox(true);
    }
    laddrs.alive = false;
    var xhr = laddrs.XHR();
    xhr.onreadystatechange=function() {
      if (xhr.readyState==4) {
        if (xhr.status!=200) {
          var e = {
            code: xhr.status,
            description: "Error pinging chat server",
          };
          laddrs.ChannelErrored(e);
        }
        else if (xhr.responseText != "OK") {
          laddrs.PingChannel();
        }
      }
    };
    console.debug("Pinging channel...");
    laddrs.Action(xhr, "ping", { 'lpt': laddrs.pingtime });
  }
  else {
    console.error("Channel socket %o is no longer alive", laddrs.socket);
    if (laddrs.socket.readyState < 2) {
      if (!laddrs.first_open && laddrs.token) {
        var newdiv = document.createElement("div");
        var now = new Date();
        newdiv.className = "system";
        newdiv.appendChild(document.createTextNode("Chat stalled."));
        newdiv.title = now.toLocaleDateString() + " " + now.toLocaleTimeString();
        cb = document.getElementById("chatbox")
        cb.appendChild(newdiv);
        cb.scrollTop = cb.scrollHeight;
      }
      console.warn("attempting to force close socket %o", laddrs.socket);
      laddrs.socket.close();
    }
    else {
      laddrs.ChannelClosed();
    }
  }
  // This is called redundantly, just to be safe.
  clearTimeout(laddrs.pinger);
  laddrs.pinger = setTimeout("laddrs.PingChannel();", laddrs.pingwait);
  laddrs.pingwait = laddrs.pingwait > 90000 ? 120000 : (laddrs.pingwait + 30000);
}

// Step 10 - Send new chats! This is what it's all about!
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
        input.value = msg;
        var e = {
          code: xhr.status,
          description: "Error sending chat message",
        };
        laddrs.ChannelErrored(e);
      }
    }
    clearTimeout(laddrs.pinger);
    laddrs.pinger = setTimeout("laddrs.PingChannel();", 30000);
    laddrs.Action(null, "send-chat", params);
    input.value = "";
    _gaq.push(['_trackEvent', 'chat', 'sent', laddrs.ladder_name]);
  }
}

// Step 11 - Handle Errors!
laddrs.ChannelErrored = function(e) {
  console.error("channel %o errored %o", laddrs.socket, e);
  _gaq.push(['_trackEvent', 'chat-error', e.code + ' ' + e.description, laddrs.ladder_name]);
  laddrs.EnableSendChatBox(false);
  // Code 401 is used when channel token expires.
  if (e.code == 401) {
    console.warn("Channel token expired. Time to refresh the connection.");
    laddrs.token = '';
    laddrs.token_refresh = true;
  }
  else {
    var newdiv = document.createElement("div");
    var now = new Date();
    newdiv.className = "system";
    newdiv.appendChild(document.createTextNode("Error occured: " + e.code + " " + e.description));
    newdiv.title = now.toLocaleDateString() + " " + now.toLocaleTimeString();
    cb = document.getElementById("chatbox")
    cb.appendChild(newdiv);
    cb.scrollTop = cb.scrollHeight;
  }
  if (laddrs.socket.readyState == 3) {
    laddrs.ChannelClosed();
  }
  else {
    clearTimeout(laddrs.pinger);
    laddrs.pinger = setTimeout("laddrs.PingChannel(20000, true);", 10000);
  }
}

// Step 12 - Reconnect when the channel closes.
laddrs.ChannelClosed = function() {
  laddrs.EnableSendChatBox(false);
  if (laddrs.socket.readyState == 3) {
    console.log("channel %o closed.", laddrs.socket)
    if (laddrs.token) {
      var newdiv = document.createElement("div");
      var now = new Date();
      newdiv.className = "system";
      newdiv.appendChild(document.createTextNode("Chat disconnected. Will retry in " + laddrs.reconnect_delay / 1000 + " seconds."));
      newdiv.title = now.toLocaleDateString() + " " + now.toLocaleTimeString();
      cb = document.getElementById("chatbox")
      cb.appendChild(newdiv);
      cb.scrollTop = cb.scrollHeight;
    }
    clearTimeout(laddrs.pinger);
    clearTimeout(laddrs.reconnect);
    laddrs.reconnect = setTimeout('laddrs.GetTokenAndOpenChannel();', laddrs.reconnect_delay);
    if (laddrs.reconnect_delay > 60000) {
      laddrs.reconnect_delay += 30000;
    }
    else {
      laddrs.reconnect_delay *= 2;
    }
    //# max out at five minute retry
    if (laddrs.reconnect_delay > 300000) {
      laddrs.reconnect_delay = 300000;
    }
  }
  else {
    console.warn("ChannelClosed called but socket %o is not closed", laddrs.socket);      clearTimeout(laddrs.pinger);
    laddrs.pinger = setTimeout("laddrs.PingChannel(10000);", 10000);
  }
}

// XmlHttpRequests make it all happen
laddrs.XHR = function() {
  return new XMLHttpRequest();
};

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
};

laddrs.POST = function(xhr, url, map) {
  var params = new Array();
  for (var i in map) {
    params.push(encodeURIComponent(i) + "=" + encodeURIComponent(map[i]));
  }
  xhr.open("POST", url, true);
  xhr.setRequestHeader("Content-type", "application/x-www-form-urlencoded");
  xhr.send(params.join("&"));
};

// UI polish is important for people to enjoy your site.
laddrs.PickColor = function() {
  return laddrs.color_options[laddrs.colors_picked++ % laddrs.color_options.length]
};

laddrs.GetTime = function(t) {
  return (t.getHours() < 10 ? "0" + t.getHours() : t.getHours()) + ":" + (t.getMinutes() < 10 ? "0" + t.getMinutes() : t.getMinutes());
};

laddrs.ThrobChatHeader = function() {
  var ch = document.getElementById("chat-header");
  var bg = ch.className;
  if (ch.className == "") {
    ch.className = "throb";
    clearTimeout(laddrs.throbber)
    laddrs.throbber = setTimeout("laddrs.ThrobChatHeader();", 1000);
  }
  else {
    ch.className = "";
    clearTimeout(laddrs.throbber)
    laddrs.throbber = setTimeout("laddrs.ThrobChatHeader();", 2000);
  }
};

laddrs.StopThrobbing = function() {
  clearTimeout(laddrs.throbber);
  document.getElementById("chat-header").className="";
};

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

function toggleSound() {
  var b = document.getElementById("sound-button")
  if (laddrs.toastSound.muted) {
    laddrs.toastSound.unmute();
    b.title = "Mute";
    b.src = "/s/soundon.png";
  }
  else {
    laddrs.toastSound.mute();
    b.title = "Unmute";
    b.src = "/s/soundoff.png";
  }
}

soundManager.url = '/s/sm2/';
soundManager.useConsole = true;
soundManager.consoleOnly = true;
soundManager.useHTML5Audio = true;
soundManager.onready(function() {
  laddrs.toastSound = soundManager.createSound({
    id:'toastSound',
    url:'/s/toast.mp3',
    autoLoad: true,
  });
  document.getElementById("sound-button").style.display = "inline";
  console.log("loaded toastSound %o", laddrs.toastSound);
});

//setInterval(function () {
//  console.debug(window.isActive ? 'active' : 'inactive');
//}, 1000);
