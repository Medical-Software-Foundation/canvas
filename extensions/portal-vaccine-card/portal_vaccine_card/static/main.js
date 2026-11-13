// My Vaccines — wires the "Print / Save as PDF" button to the browser print dialog.
document.addEventListener("DOMContentLoaded", function () {
    var printButton = document.getElementById("print-button");
    if (printButton) {
        printButton.addEventListener("click", function () {
            window.print();
        });
    }
});
