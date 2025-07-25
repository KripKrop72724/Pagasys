(function(factory) {
  var $ = window.django && window.django.jQuery ? window.django.jQuery : window.jQuery;
  if ($) {
    factory($);
  } else {
    document.addEventListener('DOMContentLoaded', function() {
      var $ = window.django && window.django.jQuery ? window.django.jQuery : window.jQuery;
      if ($) factory($);
    });
  }
})(function($) {
  function toggleGroupField() {
    var isSuper = $('#id_is_superuser').is(':checked');
    $('#id_groups').closest('.form-row').toggle(!isSuper);
    $('#id_groups').prop('disabled', isSuper);
  }
  $(function() {
    $('#id_is_superuser').on('change', toggleGroupField);
    toggleGroupField();
  });
});
