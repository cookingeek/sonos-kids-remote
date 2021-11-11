var createError = require('http-errors');
var express = require('express');
var path = require('path');
var cookieParser = require('cookie-parser');
var logger = require('morgan');
var RFID = require('./app/services/RFID.js');

var indexRouter = require('./routes/index');
var usersRouter = require('./routes/users');

var app = express();

// view engine setup
app.set('views', path.join(__dirname, 'views'));
app.set('view engine', 'pug');

app.use(logger('dev'));
app.use(express.json());
app.use(express.urlencoded({ extended: false }));
app.use(cookieParser());
app.use(express.static(path.join(__dirname, 'public')));

app.use('/', indexRouter);
app.use('/users', usersRouter);

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

module.exports = app;

var rfid = new RFID();

let { DeviceDiscovery } = require('sonos');
const Regions = require('sonos').SpotifyRegion

var defaultDevice = null;

DeviceDiscovery((device) => {
  device.deviceDescription().then((model) => {
    if (model.roomName == "Move") {
      device.setSpotifyRegion(Regions.EU);
      device.getVolume().then((test) =>{console.log(test);});
      device.setVolume(50).then((test) =>{
        //device.play("spotify:album:2ecEZ0qYMnrR8W2K4ZtxFv")
      });
      defaultDevice = device;
      //device.play();
      //device.stop();
    }
  });


});