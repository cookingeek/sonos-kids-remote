var createError = require('http-errors');
var express = require('express');
var path = require('path');
var cookieParser = require('cookie-parser');
var logger = require('morgan');
const { networkInterfaces } = require('os');

global.properties = require('./app/Config.js');
//var RFID = require('./app/services/RFID.js');
var Sonos = require('./app/services/Sonos.js');
var Remote = require('./app/services/Remote.js');
var DB = require('./app/models/Database.js');

var indexRouter = require('./routes/index');

var app = express();

// view engine setup

const nets = networkInterfaces();
const results = {}; // Or just '{}', an empty object

for (const name of Object.keys(nets)) {
  for (const net of nets[name]) {
    // Skip over non-IPv4 and internal (i.e. 127.0.0.1) addresses
    if (net.family === 'IPv4' && !net.internal) {
      if (!results[name]) {
        results[name] = [];
      }
      results[name].push(net.address);
    }
  }
}
console.log(results);
var myIp = "";
var networtInterface = properties.webserver.interface;
//discover the Ip to play local files
if (results[networtInterface] != null && results[networtInterface] != undefined) {
  myIp = results[networtInterface][0];
  //console.log("Webserver's IP: " + myIp);
}

//
//


setTimeout(function () {
  //
  //sonos.stop();
}, 5000);
//var rfid = new RFID(sonos);
//var remote = new Remote();


const run = async () => {

  app.set('views', path.join(__dirname, 'views'));
  app.set('view engine', 'pug');

  app.use(logger('dev'));
  app.use(express.json());
  app.use(express.urlencoded({ extended: false }));
  app.use(cookieParser());
  app.use(express.static(path.join(__dirname, 'public')));


  app.use('/', indexRouter);
  // catch 404 and forward to error handler
  app.use(function (req, res, next) {
    next(createError(404));
  });

  // error handler
  app.use(function (err, req, res, next) {
    // set locals, only providing error in development
    res.locals.message = err.message;
    res.locals.error = req.app.get('env') === 'development' ? err : {};

    // render the error page
    res.status(err.status || 500);
    res.render('error');
  });

  app.listen(3000);

  var db = new DB();

  var sonos = new Sonos(myIp, db);
  await sonos.init();
  //sonos.play("d7deb4e");
  var rfid = new RFID(sonos);
 //var remote = new Remote();

};

run();