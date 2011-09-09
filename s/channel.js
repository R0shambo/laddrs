laddrs = {};

laddrs.ladder_name = '';
laddrs.user_id = '';
laddrs.token = '';
laddrs.throbber = '';
laddrs.last_chat_msg = 0;

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

  toggleChatBox('block');
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
    var t = new Date();
    var c = {
      t: t.getTime(),
      n: "Player",
      m: msg,
    };
    var chat = new Array(c);
    laddrs.AddChatMessages(chat);
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
    var t = new Date(c.t);
    div.className = "message";
    div.title = t.toLocaleDateString() + " " + t.toLocaleTimeString();
    var name = document.createElement("span")
    name.className = "name";
    name.innerText = c.n + ": ";
    var text = document.createElement("span")
    text.className = "chatmsg";
    text.innerText = c.m;
    cb.appendChild(div);
    div.appendChild(name);
    div.appendChild(text);
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
  laddrs.Action(null, "get-chat-history", params);
}
laddrs.ChannelErrored = function() {
  document.getElementById("chatbox").innerHTML="Channel Error!";
}
laddrs.ChannelMessaged = function(m) {
  var msg = JSON.parse(m.data);
  if (msg.chat) {
    laddrs.AddChatMessages(msg.chat);
  }
}
laddrs.ChannelClosed = function() {
  document.getElementById("chatbox").innerHTML="Channel Closed!";
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
