/**
 *
 */
 'use strict'
 const Datastore = require('nedb');
 var db = {};
 db = new Datastore({
   filename: 'db/' + properties.db.filename,
   autoload: true
 });
 class Database {
 
   constructor() {
     db.loadDatabase();
   }
 
   create(data, callback) {
     db.insert(data, callback);
   }
 
   update(query, update, callback) {
     db.update(query, {
       $set: update
     }, {}, callback)
   }
 
   remove(id, callback) {
     db.remove({
       _id: id
     }, {}, callback);
   }
 
   findById(id, callback) {
     db.find({
       _id: id
     }, callback);
   }
 }
 
 module.exports = Database;