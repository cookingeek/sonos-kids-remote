var express = require('express');
var router = express.Router();
var DB = require('../app/models/Database');
/* GET home page. */
router.get('/', function(req, res, next) {
  var db = new DB();
 var cards = db.findAll();
  res.render('index', { title: 'Express', cards: cards });
});


module.exports = router;

