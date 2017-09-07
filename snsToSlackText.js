// Unfortunately this is slightly-modified from code I found online, but can't re-find
// at the moment.  If you're the author please let me know; you saved me a couple of
// hours of coding :)

//
// AWS Lambda script.  Gets Cloudwatch alarm SNS trigger and 
// passes the relevant information on to a Slack webhook.
//

//  This is modified to handle RDS Event Notifications, which don't do JSON but 
//  just plain text.
//

const https = require('https');
const url = require('url');
const slack_url_base = 'https://hooks.slack.com/services/';
const slack_url_post = 'T1AJFN73J/B41NCTLN7/1wLkwfpnWIhaakGzw5qLv6yI';
const slack_req_opts = url.parse(slack_url_base + slack_url_post);
slack_req_opts.method = 'POST';
slack_req_opts.headers = {
    'Content-Type': 'application/json'
};

exports.handler = (event, context, callback) => {
    //console.log("start test-func here");
    (event.Records || []).forEach(function(rec) {
        if (rec.Sns) {
            var req = https.request(slack_req_opts, function(res) {
                if (res.statusCode === 200) {
                    context.succeed('posted to slack');
                } else {
                    context.fail('status code: ' + res.statusCode);
                }
            });

            req.on('error', function(e) {
                console.log('problem with request: ' + e.message);
                context.fail(e.message);
            });

            var text_msg = JSON.stringify(rec.Sns.Message, null, '  ');
            
            // By default, we want to send this alert
            var send_msg = true;
            
            try {
                var msg_data = [];
                var msg = rec.Sns.Message;
                var parsed = JSON.parse(rec.Sns.Message);
                
                try {
                    var time = parsed['Event Time'];
                    var eventId = parsed['Event ID'].split('#')[1];
                    var message = parsed['Event Message'];
                    var sourceId = parsed['Source ID'];
                    
                    msg_data.push(sourceId + " - " + time);
                    msg_data.push(message + " (" + eventId + ")");
                } catch(err) {
                    console.log("Message format incorrect");
                    console.log(err);
                    //send_msg = false;
                    msg_data.push(msg);
                }

                text_msg = msg_data.join("\n");
            } catch (e) {
                console.log(e);
            }
            
            // Change color based on subject being ALARM: or OK:
            // Assume it's "ALARM:"
            var color = "#D00000";
            if (rec.Sns.Subject.indexOf("OK:") !== -1) {
                color = "#00D000";
            }

            var params = {
                attachments: [{
                    fallback: text_msg,
                    color: color,
                    fields: [{
                        "value": text_msg,
                        "short": false
                    }]
                }]
            };
            
            // Only send alert if it hasn't been nullified.
            if (send_msg) {
                req.write(JSON.stringify(params));
                req.end();
            }
        } else {
            console.log("no Sns");
        }
    });
};
