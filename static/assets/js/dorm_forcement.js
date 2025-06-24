const user_agreement_path = '/agreement'
const dorm_path = '/dormitory/agreement';
const modpw_path = '/modpw';
const query_path = '/dormitory/agreement-query-fixme';

function skipThisPage() {
    var current_url = window.location.pathname;
    return current_url.includes(dorm_path) || current_url.includes(user_agreement_path) || current_url.includes(modpw_path);
}

function getAgreementState() {
    return fetch(query_path)
        .then(response => response.json())
        .then(data => {
            // Bad design:
            // If user do not have to sign,
            // or user has signed, return is not empty.
            return data.length > 0;
        })
        .catch(error => {
            console.error('Error fetching agreement state:', error);
            return true; // Pretend user has signed on network error.
        });
}

$(function() {
    if (!skipThisPage()) {
        getAgreementState().then(signed => {
            if (!signed) {
                window.location.href = dorm_path;
            }
        });
    }
});
