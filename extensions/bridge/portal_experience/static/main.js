// Hello!

function ready(fn) {
  if (document.readyState !== 'loading') {
    fn();
  } else {
    document.addEventListener('DOMContentLoaded', fn);
  }
}

// When the bridge modal completes, the result will include a
// ServiceEligibility id. You should send that to your plugin so it can be
// stored. This function mimics that. When you add the bridge experience, make
// this same request, but with the returned ServiceEligibility id.
ready(function () {
  var data = {
    "ServiceEligibility": {
      "id": "abc123"
    }
  }

  fetch('/plugin-io/api/bridge/app/store-eligibility-id', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  });
});
