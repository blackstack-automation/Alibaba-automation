function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]').content;
}

async function csrfFetch(url, options = {}) {
    const headers = Object.assign({}, options.headers, { "X-CSRFToken": csrfToken() });
    return fetch(url, Object.assign({}, options, { headers }));
}

function requestConfirm(form, message) {
    window.dispatchEvent(
        new CustomEvent("open-confirm-modal", { detail: { message, form } })
    );
    return false;
}
