const dorm_path = '/dormitory/agreement';
const query_path = '/dormitory/agreement-query';

function currentIsDormPage() {
    var current_url = window.location.pathname;
    return current_url.includes(dorm_path);
}

function getAgreementState() {
    // Return the fetch promise
    return fetch(query_path)
        .then(response => response.json())
        .then(data => {
            return data.signed;
        })
        .catch(error => {
            console.error('Error fetching agreement state:', error);
            return false;
        });
}

$(function() {
    if (!currentIsDormPage()) {
        getAgreementState().then(signed => {
            if (!signed) {
                window.location.href = dorm_path;
            }
        });
    }
});
