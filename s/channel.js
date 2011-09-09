laddrs = {};

laddrs.ladder_name = '';
laddrs.user_id = '';
laddrs.token = '';

laddrs.XHR = function() {
  if (window.XMLHttpRequest) {
    return new XMLHttpRequest();
  } else if (window.ActiveXObject) {
    return new ActiveXObject("Microsoft.XMLHTTP");
  }
}

laddrs.POST = function(xhr, url, params) {
  var content = params;
  xhr.open("POST", url, true);
  xhr.setRequestHeader("Content-type", "application/x-www-form-urlencoded");
  xhr.send(content);
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
  laddrs.POST(xhr, "/channel",
      "action=get_token&ladder=" + laddrs.ladder_name +
      "&user_id=" + laddrs.user_id);
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

  document.getElementById("chatbox").innerHTML=laddrs.token;
  toggleChatBox('block');
}

laddrs.ChannelOpened = function() {
  document.getElementById("chatbox").innerHTML="Channel Opened!";
}
laddrs.ChannelErrored = function() {
  document.getElementById("chatbox").innerHTML="Channel Error!";
}
laddrs.ChannelMessaged = function() {
  document.getElementById("chatbox").innerHTML="Channel Messaged!";
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
