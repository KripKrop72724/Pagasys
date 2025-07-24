(function($) {
  function toggleGroupField() {
    var isSuper = $('#id_is_superuser').is(':checked');
    $('#id_groups').closest('.form-row').toggle(!isSuper);
  }
  $(document).ready(function() {
    $('#id_is_superuser').change(toggleGroupField);
    toggleGroupField();
  });
})(django.jQuery);
