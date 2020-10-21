var createError = require('http-errors');
var express = require('express');
var path = require('path');
var cookieParser = require('cookie-parser');
var logger = require('morgan');
var PropertiesReader = require('properties-reader');
var prop = PropertiesReader('config/sonos-remote-4kids.properties');

var i18next = require("i18next");
var middleware = require('i18next-http-middleware');
var FilesystemBackend = require('i18next-node-fs-backend');

i18next.use(FilesystemBackend).use(middleware.LanguageDetector).init({
 	ns: 'resource',
 	defaultNS:'resource',
	preload: ['de', 'en'],
	supportedLngs: ['de','en'],
    fallbackLng: 'de',
	debug: true,
    ignoreRoutes: ['/css', '/img', 'js', 'lib', 'views'],
    resGetPath: __dirname + '/locales/{{lng}}/{{ns}}.json',
 	backend: {
 		loadPath: path.join(__dirname + '/locales/{{lng}}/{{ns}}.json')
 	}
});
 
var indexRouter = require('./routes/index');
var usersRouter = require('./routes/users');

var app = express();

app.use(
  middleware.handle(i18next, {
  })
)

app.use(express.static(__dirname + '/node_modules/bootstrap/dist'));
app.use(express.static(__dirname + '/node_modules/jquery/dist'));
app.use(express.static(__dirname + '/node_modules/@popperjs/core/dist/umd'));
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
app.use(function(req, res, next) {
  next(createError(404));
});

// error handler
app.use(function(err, req, res, next) {
  // set locals, only providing error in development
  res.locals.message = err.message;
  res.locals.error = req.app.get('env') === 'development' ? err : {};

  // render the error page
  res.status(err.status || 500);
  res.render('error');
});

module.exports = app;
