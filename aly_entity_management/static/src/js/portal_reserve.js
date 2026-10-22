/** Portal "Request a reservation" form: show the end date only when renting. */
function alyToggleReservationType(select) {
    const form = select.closest("form");
    const isSale = select.value === "sale";
    form.querySelectorAll(".o_aly_lease_only").forEach((el) => el.classList.toggle("d-none", isSale));
    form.querySelectorAll(".o_aly_sale_only").forEach((el) => el.classList.toggle("d-none", !isSale));
    const dateEnd = form.querySelector("input[name='date_end']");
    if (dateEnd) {
        dateEnd.required = !isSale;
        if (isSale) {
            dateEnd.value = "";
        }
    }
}

document.addEventListener("change", (ev) => {
    if (ev.target.matches && ev.target.matches("select.o_aly_contract_type")) {
        alyToggleReservationType(ev.target);
    }
});
